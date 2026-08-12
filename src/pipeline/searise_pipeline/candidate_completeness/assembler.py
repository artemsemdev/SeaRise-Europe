"""Deterministic, immutable assembly of the complete Phase 1 synthetic fixture."""

from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, NoReturn

from .byte_gate import CandidateByteSummary, validate_candidate_root
from .qa_report import build_synthetic_fixture_gate_report
from .validator import CandidateContractError, load_candidate_bytes, validate_candidate_document

CONTRACT_ROOT = Path(__file__).resolve().parents[4] / "contracts/candidate-completeness/v2"
_TEMPLATE = CONTRACT_ROOT / "fixtures/valid/engineering-candidate.json"
_PRE_GATE_COUNT = 51
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
_ENTRY_KEYS = {"artifactId", "gridId", "parityId", "stacAssets", "payloadSha256"}
_CLAIMS = {
    "formatValid": False,
    "ownerApproval": False,
    "production": False,
    "publication": False,
    "scientific": False,
    "syntheticFixture": True,
}
_RIGHTS = {"redistribution": "allowed", "syntheticOnly": True}
_ASSEMBLY_LOCK = threading.Lock()


class CandidateAssemblyError(ValueError):
    """The synthetic candidate could not be assembled without broadening claims."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.cleanup_error: str | None = None
        super().__init__(f"{code}: {message}")

    def preserve_cleanup_error(self, cleanup: "CandidateAssemblyError") -> None:
        """Keep the primary failure while making an impossible cleanup explicit."""
        self.cleanup_error = str(cleanup)
        self.args = (f"{self.args[0]}; cleanup failure: {cleanup}",)


@dataclass(frozen=True)
class CandidateAssemblySummary:
    """Identity of one locally promoted, still non-publishable candidate."""

    candidate_id: str
    artifact_count: int
    artifact_bytes: int
    manifest_sha256: str
    output_directory: Path
    production: bool = False
    publication: bool = False


@dataclass
class _StageOwnership:
    """Device/inode ledger for every entry created below one held stage root."""

    root: tuple[int, int]
    directories: dict[PurePosixPath, tuple[int, int]]
    files: dict[PurePosixPath, tuple[int, int]]


def _fail(code: str, message: str) -> NoReturn:
    raise CandidateAssemblyError(code, message)


def _canonical(document: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CandidateAssemblyError("assembly-input", "input is not canonical JSON") from exc


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_stable_file(path: Path, *, code: str, maximum_bytes: int) -> bytes:
    """Read one bounded, single-link file and reject a concurrent replacement."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > maximum_bytes
        ):
            _fail(code, "input must be one bounded regular file")
        raw = bytearray()
        while len(raw) < before.st_size:
            chunk = os.read(descriptor, before.st_size - len(raw))
            if not chunk:
                _fail(code, "input ended while it was read")
            raw.extend(chunk)
        if os.read(descriptor, 1) or _identity(os.fstat(descriptor)) != _identity(before):
            _fail(code, "input changed while it was read")
        return bytes(raw)
    except CandidateAssemblyError:
        raise
    except OSError as exc:
        raise CandidateAssemblyError(code, "input cannot be opened safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _bounded_input_kind(path: Path, *, code: str) -> None:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise CandidateAssemblyError(code, "input cannot be inspected safely") from exc
    if not stat.S_ISREG(metadata.st_mode):
        _fail(code, "input must be one bounded regular file")


def _read_bound_receipt(path: Path) -> bytes:
    _bounded_input_kind(path, code="assembly-receipt")
    return _read_stable_file(path, code="assembly-receipt", maximum_bytes=_MAX_RECEIPT_BYTES)


def _payload_bytes(fixture_id: str, entry: Mapping[str, Any]) -> bytes:
    return _canonical(
        {
            "artifactId": entry.get("artifactId"),
            "fixtureId": fixture_id,
            "gridId": entry.get("gridId"),
            "parityId": entry.get("parityId"),
            "stacAssets": entry.get("stacAssets"),
            "synthetic": True,
        }
    )


def _scenario_horizon(artifact_id: str) -> tuple[str, int] | None:
    match = re.fullmatch(
        r"(?:stac-item|projection)-(ssp1-26|ssp2-45|ssp5-85)-(2030|2050|2100)"
        r"(?:-cog|-pmtiles)?",
        artifact_id,
    )
    return (match.group(1), int(match.group(2))) if match else None


def _expected_assets(scenario: str, horizon: int) -> dict[str, str]:
    return {
        "analysis": f"analysis/{scenario}/{horizon}.tif",
        "table": "analysis/projections.parquet",
        "visual": f"layers/{scenario}/{horizon}.pmtiles",
    }


def _load_inputs(
    receipt_path: Path,
) -> tuple[dict[str, Any], str, str, dict[str, bytes]]:
    try:
        receipt = load_candidate_bytes(_read_bound_receipt(receipt_path))
    except CandidateAssemblyError:
        raise
    except ValueError as exc:
        raise CandidateAssemblyError("assembly-receipt", "receipt is not strict JSON") from exc
    expected_keys = {
        "schemaVersion",
        "fixtureId",
        "candidateTemplateSha256",
        "expectedManifestSha256",
        "gridId",
        "claims",
        "rights",
        "inputs",
    }
    if set(receipt) != expected_keys or receipt.get("schemaVersion") != 1:
        _fail("assembly-receipt", "receipt shape or version differs")
    fixture_id = receipt.get("fixtureId")
    grid_id = receipt.get("gridId")
    expected_manifest = receipt.get("expectedManifestSha256")
    if not isinstance(fixture_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", fixture_id):
        _fail("assembly-receipt", "fixtureId is invalid")
    if not isinstance(grid_id, str) or not re.fullmatch(r"[a-f0-9]{64}", grid_id):
        _fail("grid-identity", "gridId must be one lowercase SHA-256")
    if not isinstance(expected_manifest, str) or not re.fullmatch(
        r"[a-f0-9]{64}", expected_manifest
    ):
        _fail("assembly-receipt", "expected manifest identity is invalid")
    if receipt.get("claims") != _CLAIMS:
        _fail("fixture-claims", "fixture claims must remain explicitly false")
    if receipt.get("rights") != _RIGHTS:
        _fail("fixture-rights", "fixture redistribution rights are invalid")

    _bounded_input_kind(_TEMPLATE, code="assembly-template")
    template_raw = _read_stable_file(
        _TEMPLATE, code="assembly-template", maximum_bytes=_MAX_TEMPLATE_BYTES
    )
    if receipt.get("candidateTemplateSha256") != _sha256(template_raw):
        _fail("assembly-input-hash", "candidate template SHA-256 differs")
    candidate = load_candidate_bytes(template_raw)
    validate_candidate_document(candidate)
    required = candidate["artifacts"][:_PRE_GATE_COUNT]
    entries = receipt.get("inputs")
    if not isinstance(entries, list) or len(entries) != _PRE_GATE_COUNT:
        _fail("assembly-inputs", "receipt must contain exactly 51 pre-gate inputs")
    if [entry.get("artifactId") if isinstance(entry, Mapping) else None for entry in entries] != [
        item["artifactId"] for item in required
    ]:
        _fail("assembly-inputs", "input identities or order differ from the contract")

    payloads: dict[str, bytes] = {}
    parity: dict[tuple[str, int], dict[str, str]] = {}
    # Keep this loop usable by the project's Python 3.9 minimum version.
    for index in range(_PRE_GATE_COUNT):
        entry = entries[index]
        artifact = required[index]
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            _fail("assembly-inputs", "each input must have the exact fixture shape")
        raw = _payload_bytes(fixture_id, entry)
        if entry["payloadSha256"] != _sha256(raw):
            _fail("assembly-input-hash", f"input SHA-256 differs: {entry['artifactId']}")
        artifact_id = artifact["artifactId"]
        pair = _scenario_horizon(artifact_id)
        role = artifact["role"]
        needs_grid = role in {
            "projection-geoparquet",
            "projection-analysis-cog",
            "projection-visual-pmtiles",
            "stac-item",
        }
        if entry["gridId"] != (grid_id if needs_grid else None):
            _fail("grid-drift", f"input grid identity differs: {artifact_id}")
        if pair and role in {"projection-analysis-cog", "projection-visual-pmtiles", "stac-item"}:
            expected_parity = f"{pair[0]}-{pair[1]}"
            if entry["parityId"] != expected_parity:
                _fail("parity-mismatch", f"input parity identity differs: {artifact_id}")
            parity.setdefault(pair, {})[role] = entry["parityId"]
        elif entry["parityId"] is not None:
            _fail("parity-mismatch", f"unexpected parity identity: {artifact_id}")
        if role == "stac-item":
            assert pair is not None
            if entry["stacAssets"] != _expected_assets(*pair):
                _fail("stac-link", f"STAC fixture links differ: {artifact_id}")
        elif entry["stacAssets"] is not None:
            _fail("stac-link", f"unexpected STAC fixture links: {artifact_id}")
        payloads[artifact_id] = raw
    expected_roles = {"projection-analysis-cog", "projection-visual-pmtiles", "stac-item"}
    if len(parity) != 9 or any(set(roles) != expected_roles for roles in parity.values()):
        _fail("parity-mismatch", "all nine projection pairs must have complete parity")
    return candidate, fixture_id, expected_manifest, payloads


def _candidate_bytes(
    candidate: dict[str, Any], fixture_id: str, payloads: dict[str, bytes]
) -> tuple[bytes, dict[str, bytes]]:
    del fixture_id
    report_json, report_markdown = build_synthetic_fixture_gate_report(candidate)
    payloads = {
        **payloads,
        "release-gate-report-json": report_json,
        "release-gate-report-markdown": report_markdown,
    }
    artifacts = candidate["artifacts"]
    for artifact in artifacts[:53]:
        raw = payloads[artifact["artifactId"]]
        artifact.update(byteSize=len(raw), sha256=_sha256(raw))
    subjects = sorted(
        ({"path": item["path"], "sha256": item["sha256"]} for item in artifacts[:53]),
        key=lambda item: item["path"],
    )
    candidate["checksumInventory"]["subjects"] = subjects
    checksums = "".join(f"{item['sha256']}  {item['path']}\n" for item in subjects).encode()
    artifacts[53].update(byteSize=len(checksums), sha256=_sha256(checksums))
    payloads["checksums"] = checksums
    validate_candidate_document(candidate)
    return _canonical(candidate), payloads


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _directory_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _open_trusted_output_parent(output: Path) -> tuple[Path, int]:
    """Open one absolute, symlink-free parent controlled by the current user."""
    if not output.is_absolute() or ".." in output.parts:
        _fail("assembly-publication", "candidate output must be one absolute path")
    parent = output.parent
    descriptor = -1
    try:
        descriptor = os.open(parent.anchor, _directory_flags())
        for part in parent.parts[1:]:
            child = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
            _fail(
                "assembly-publication",
                "candidate output parent must be owner-controlled and not group/world writable",
            )
        return parent, descriptor
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _entry_identity(parent: int, name: str) -> tuple[int, int] | None:
    try:
        return _directory_identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _open_directory(parent: int, parts: Iterable[str]) -> int:
    descriptor = os.dup(parent)
    try:
        for part in parts:
            child = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError:
        os.close(descriptor)
        raise


def _open_owned_directory(
    root: int, logical: PurePosixPath, ownership: _StageOwnership
) -> int:
    """Open only directories whose current entries match the creation ledger."""
    descriptor = os.dup(root)
    current = PurePosixPath()
    try:
        for part in logical.parts:
            current /= part
            expected = ownership.directories.get(current)
            if expected is None or _entry_identity(descriptor, part) != expected:
                _fail("foreign-replacement", f"staging directory identity differs: {current}")
            child = os.open(part, _directory_flags(), dir_fd=descriptor)
            if (
                _directory_identity(os.fstat(child)) != expected
                or _entry_identity(descriptor, part) != expected
            ):
                os.close(child)
                _fail("foreign-replacement", f"staging directory changed while opened: {current}")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _reserve_owned_directory(
    parent: int, prefix: str, mode: int
) -> tuple[str, int, tuple[int, int]]:
    """Reserve a private directory and bind its held descriptor to the entry."""
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(16)}"
        try:
            created = _mkdir_exclusive(parent, name, mode)
        except FileExistsError:
            continue
        descriptor = -1
        try:
            descriptor = os.open(name, _directory_flags(), dir_fd=parent)
            if (
                _directory_identity(os.fstat(descriptor)) != created
                or _entry_identity(parent, name) != created
            ):
                _fail("foreign-replacement", f"private staging directory was replaced: {name}")
            return name, descriptor, created
        except Exception:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            # The exact child is known after mkdir. Atomically move only that
            # identity to a retained private quarantine before rethrowing; a
            # replacement is preserved and an unprovable cleanup stays visible.
            try:
                _quarantine_owned_entry(parent, name, created)
            except (CandidateAssemblyError, OSError):
                pass
            raise
    _fail("assembly-publication", "cannot reserve a private staging directory")


def _create_owned_directory(
    parent: int, name: str, mode: int = 0o755
) -> tuple[int, tuple[int, int]]:
    """Create privately, then atomically promote the exact held directory."""
    private, descriptor, created = _reserve_owned_directory(
        parent, ".candidate-directory-", mode
    )
    try:
        if (
            _directory_identity(os.fstat(descriptor)) != created
            or _entry_identity(parent, private) != created
        ):
            _fail("foreign-replacement", f"private staging directory changed: {name}")
        _rename_no_overwrite(parent, private, parent, name)
        _sync_directory(parent)
        if _entry_identity(parent, name) != created:
            _fail("foreign-replacement", f"promoted staging directory was replaced: {name}")
        return descriptor, created
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _ensure_owned_directory(
    root: int, logical: PurePosixPath, ownership: _StageOwnership
) -> int:
    descriptor = os.dup(root)
    current = PurePosixPath()
    try:
        for part in logical.parts:
            current /= part
            expected = ownership.directories.get(current)
            if expected is None:
                child, expected = _create_owned_directory(descriptor, part)
                ownership.directories[current] = expected
            else:
                if _entry_identity(descriptor, part) != expected:
                    _fail("foreign-replacement", f"staging directory identity differs: {current}")
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
                if (
                    _directory_identity(os.fstat(child)) != expected
                    or _entry_identity(descriptor, part) != expected
                ):
                    os.close(child)
                    _fail(
                        "foreign-replacement",
                        f"staging directory changed while opened: {current}",
                    )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _logical(path: str) -> PurePosixPath:
    logical = PurePosixPath(path)
    if logical.is_absolute() or any(part in {"", ".", ".."} for part in logical.parts):
        _fail("assembly-publication", "candidate artifact path is unsafe")
    return logical


def _write_new(root: int, path: str, raw: bytes, ownership: _StageOwnership) -> None:
    """Create one stage file through the held stage-root descriptor."""
    logical = _logical(path)
    parent = _ensure_owned_directory(root, logical.parent, ownership)
    descriptor = -1
    private = f".candidate-file-{secrets.token_hex(16)}"
    created: tuple[int, int] | None = None
    try:
        descriptor = os.open(
            private,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        created = _directory_identity(os.fstat(descriptor))
        if _entry_identity(parent, private) != created:
            _fail("foreign-replacement", f"private staging file was replaced: {logical}")
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("candidate write made no progress")
            offset += written
        os.fsync(descriptor)
        if _entry_identity(parent, private) != created:
            _fail("foreign-replacement", f"private staging file changed: {logical}")
        _rename_no_overwrite(parent, private, parent, logical.name)
        _sync_directory(parent)
        if _entry_identity(parent, logical.name) != created:
            _fail("foreign-replacement", f"promoted staging file was replaced: {logical}")
        ownership.files[logical] = created
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if created is not None:
            for current in (private, logical.name):
                if (
                    current != logical.name or logical not in ownership.files
                ) and _entry_identity(parent, current) == created:
                    _quarantine_owned_entry(parent, current, created)
        os.close(parent)


def _stage_directories(paths: Iterable[str]) -> list[PurePosixPath]:
    return sorted(
        {PurePosixPath(part) for path in paths for part in _logical(path).parents if part.parts},
        key=lambda item: (len(item.parts), item.as_posix()),
        reverse=True,
    )


def _chmod_file(root: int, path: str, mode: int, ownership: _StageOwnership) -> None:
    logical = _logical(path)
    expected = ownership.files.get(logical)
    if expected is None:
        _fail("foreign-replacement", f"staging file is not owned: {logical}")
    parent = _open_owned_directory(root, logical.parent, ownership)
    descriptor = -1
    try:
        if _entry_identity(parent, logical.name) != expected:
            _fail("foreign-replacement", f"staging file identity differs: {logical}")
        descriptor = os.open(
            logical.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
        if (
            _directory_identity(os.fstat(descriptor)) != expected
            or _entry_identity(parent, logical.name) != expected
        ):
            _fail("foreign-replacement", f"staging file changed while opened: {logical}")
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)


def _freeze(root: int, paths: Iterable[str], ownership: _StageOwnership) -> None:
    paths = tuple(paths)
    for path in paths:
        _chmod_file(root, path, 0o444, ownership)
    for directory_path in _stage_directories(paths):
        descriptor = _open_owned_directory(root, directory_path, ownership)
        try:
            os.fchmod(descriptor, 0o555)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    # Darwin RENAME_EXCL needs the moved directory to remain writable. Its
    # descriptor is frozen immediately after promotion.
    os.fchmod(root, 0o755)
    os.fsync(root)


def _thaw(root: int, ownership: _StageOwnership) -> None:
    os.fchmod(root, 0o700)
    os.fsync(root)
    for directory_path in sorted(
        ownership.directories, key=lambda item: (len(item.parts), item.as_posix())
    ):
        try:
            descriptor = _open_owned_directory(root, directory_path, ownership)
        except (CandidateAssemblyError, OSError):
            continue
        try:
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _sync_directory(descriptor: int) -> None:
    os.fsync(descriptor)


def _fsync_tree(root: int, paths: Iterable[str], ownership: _StageOwnership) -> None:
    """Synchronize child directories before their parents through held descriptors."""
    for directory_path in _stage_directories(paths):
        descriptor = _open_owned_directory(root, directory_path, ownership)
        try:
            _sync_directory(descriptor)
        finally:
            os.close(descriptor)
    _sync_directory(root)


def _sync_rename_parents(source_parent: int, destination_parent: int) -> None:
    """Persist metadata changed by a cross-directory rename on both supported OSes."""
    _sync_directory(source_parent)
    _sync_directory(destination_parent)


def _rename_no_overwrite(source_parent: int, source: str, output_parent: int, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename, flag = libc.renameatx_np, 4
    elif sys.platform.startswith("linux"):
        rename, flag = libc.renameat2, 1
    else:
        _fail("assembly-publication", "exclusive directory rename is unsupported")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if (
        rename(
            source_parent,
            os.fsencode(source),
            output_parent,
            os.fsencode(target),
            flag,
        )
        != 0
    ):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), target)


def _rename_exchange(left_parent: int, left: str, right_parent: int, right: str) -> None:
    """Atomically exchange two existing entries without requiring either child writable."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename, flag = libc.renameatx_np, 2
    elif sys.platform.startswith("linux"):
        rename, flag = libc.renameat2, 2
    else:
        _fail("assembly-publication", "atomic directory exchange is unsupported")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if (
        rename(
            left_parent,
            os.fsencode(left),
            right_parent,
            os.fsencode(right),
            flag,
        )
        != 0
    ):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), right)


def _mkdir_exclusive(parent: int, name: str, mode: int) -> tuple[int, int]:
    """Create a private child without exposing a predictable mkdir hook boundary."""
    libc = ctypes.CDLL(None, use_errno=True)
    mkdir = libc.mkdirat
    mkdir.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    mkdir.restype = ctypes.c_int
    if mkdir(parent, os.fsencode(name), mode) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), name)
    created = _entry_identity(parent, name)
    if created is None:
        _fail("foreign-replacement", "private staging directory disappeared")
    return created


def _make_staging(parent: int) -> tuple[str, int, tuple[int, int]]:
    return _reserve_owned_directory(parent, ".candidate-assembly-", 0o700)


def _entry_matches(directory: int, name: str, expected: tuple[int, int]) -> bool:
    try:
        observed = os.stat(name, dir_fd=directory, follow_symlinks=False)
        return _directory_identity(observed) == expected
    except FileNotFoundError:
        return False


def _commit_matches(parent_path: Path, parent: int, name: str, stage: int) -> bool:
    """Check the pathname parent and final entry at the publication commit point."""
    try:
        current_parent = os.stat(parent_path, follow_symlinks=False)
    except OSError:
        return False
    parent_matches = _directory_identity(current_parent) == _directory_identity(os.fstat(parent))
    return parent_matches and _entry_matches(parent, name, _directory_identity(os.fstat(stage)))


def _quarantine_owned_entry(
    parent: int, name: str, expected: tuple[int, int]
) -> bool:
    """Atomically isolate exact owned bytes; retain them because POSIX lacks conditional unlink."""
    for _ in range(128):
        quarantine = f".candidate-owned-{secrets.token_hex(16)}"
        try:
            _rename_no_overwrite(parent, name, parent, quarantine)
        except FileNotFoundError:
            return True
        except FileExistsError:
            continue
        _sync_directory(parent)
        if not _entry_matches(parent, quarantine, expected):
            if _entry_identity(parent, name) is None:
                _rename_no_overwrite(parent, quarantine, parent, name)
                _sync_directory(parent)
            return False
        return True
    _fail("assembly-publication", "cannot reserve an owned cleanup quarantine")


def _remove_owned_stage(root: int, ownership: _StageOwnership) -> None:
    """Remove only exact owned entries and durably preserve every replacement."""
    _thaw(root, ownership)
    for logical, expected in sorted(ownership.files.items(), key=lambda item: item[0].as_posix()):
        try:
            parent = _open_owned_directory(root, logical.parent, ownership)
        except (CandidateAssemblyError, OSError):
            continue
        try:
            _quarantine_owned_entry(parent, logical.name, expected)
        finally:
            os.close(parent)
    for logical, expected in sorted(
        ownership.directories.items(),
        key=lambda item: (len(item[0].parts), item[0].as_posix()),
        reverse=True,
    ):
        try:
            parent = _open_owned_directory(root, logical.parent, ownership)
        except (CandidateAssemblyError, OSError):
            continue
        try:
            _quarantine_owned_entry(parent, logical.name, expected)
        finally:
            os.close(parent)


def _cleanup_staging(
    parent: int,
    temporary_name: str,
    temporary: int,
    temporary_identity: tuple[int, int],
    stage: int,
    stage_name: str | None,
    ownership: _StageOwnership | None,
) -> None:
    """Remove only the held staging tree; a replacement is intentionally retained."""
    if stage >= 0 and stage_name is not None and ownership is not None:
        if _entry_matches(temporary, stage_name, ownership.root):
            _remove_owned_stage(stage, ownership)
            _quarantine_owned_entry(temporary, stage_name, ownership.root)
    # Retain one high-entropy mode-0700 wrapper. POSIX has no conditional rmdir,
    # so deleting even an empty name would reopen a same-UID replacement race.
    if _entry_matches(parent, temporary_name, temporary_identity):
        os.fchmod(temporary, 0o700)
        os.fsync(temporary)
        _sync_directory(parent)


def _rollback_owned_promotion(
    parent: int,
    output_name: str,
    temporary: int,
    stage: int,
    ownership: _StageOwnership,
) -> str | None:
    """Durably move our promoted inode away without touching a foreign final directory."""
    stage_identity = _directory_identity(os.fstat(stage))
    if not _entry_matches(parent, output_name, stage_identity):
        return None
    public_quarantine: str | None = None
    placeholder = -1
    placeholder_identity: tuple[int, int] | None = None
    exchanged = False
    # Darwin's exclusive rename rejects a mode-0555 directory. Exchanging the
    # final with an exact owned empty slot moves it away without thawing it and
    # cannot overwrite an existing entry.
    last_error: OSError | None = None
    try:
        try:
            public_quarantine, placeholder, placeholder_identity = _reserve_owned_directory(
                parent, ".candidate-rollback-", 0o700
            )
        except (CandidateAssemblyError, OSError) as exc:
            raise CandidateAssemblyError(
                "assembly-rollback",
                "owned failed candidate remains at the public output because rollback "
                "slot reservation failed",
            ) from exc
        for _ in range(1024):
            try:
                stage_matches = _entry_matches(parent, output_name, stage_identity)
                slot_matches = _entry_matches(
                    parent, public_quarantine, placeholder_identity
                )
            except OSError as exc:
                raise CandidateAssemblyError(
                    "assembly-rollback",
                    "owned failed candidate remains at the public output because rollback "
                    "authority could not be inspected",
                ) from exc
            if not stage_matches:
                return None
            if not slot_matches:
                raise CandidateAssemblyError(
                    "assembly-rollback",
                    "owned failed candidate remains at the public output because rollback "
                    "slot identity differs",
                )
            try:
                _rename_exchange(parent, output_name, parent, public_quarantine)
            except OSError as exc:
                last_error = exc
                continue
            exchanged = True
            break
        if not exchanged:
            detail = f"; last retry error was {last_error}" if last_error is not None else ""
            raise CandidateAssemblyError(
                "assembly-rollback",
                "owned failed candidate remains at the public output after bounded quarantine "
                f"attempts{detail}",
            ) from last_error
        candidate_matches = _entry_matches(parent, public_quarantine, stage_identity)
        placeholder_matches = _entry_matches(parent, output_name, placeholder_identity)
        if placeholder_matches:
            try:
                os.rmdir(output_name, dir_fd=parent)
            except OSError as exc:
                raise CandidateAssemblyError(
                    "assembly-rollback",
                    "owned empty rollback placeholder remains at the public output",
                ) from exc
        if not candidate_matches or not placeholder_matches:
            _fail("assembly-publication", "failed candidate exchange identity differs")
        _sync_directory(parent)
        # The invalid candidate is already absent from the public name. Thawing
        # and moving it under the retained private wrapper are cleanup-only.
        os.fchmod(stage, 0o700)
        os.fsync(stage)
        rollback_name = f".candidate-rollback-{secrets.token_hex(16)}"
        _rename_no_overwrite(parent, public_quarantine, temporary, rollback_name)
        if not _entry_matches(temporary, rollback_name, stage_identity):
            _fail("assembly-publication", "failed candidate quarantine identity differs")
        _sync_rename_parents(parent, temporary)
        return rollback_name
    finally:
        if (
            not exchanged
            and public_quarantine is not None
            and placeholder_identity is not None
        ):
            try:
                if _entry_matches(parent, public_quarantine, placeholder_identity):
                    os.rmdir(public_quarantine, dir_fd=parent)
                    _sync_directory(parent)
            except OSError:
                pass
        if placeholder >= 0:
            try:
                os.close(placeholder)
            except OSError:
                pass


def _final_publication_gate(
    parent_path: Path,
    parent: int,
    output_name: str,
    stage: int,
    expected: CandidateByteSummary,
) -> CandidateByteSummary:
    """Return only one fully revalidated tree still bound to the final pathname."""
    expected_parent = _directory_identity(os.fstat(parent))
    expected_stage = _directory_identity(os.fstat(stage))

    def authority() -> int:
        current_parent = os.stat(parent_path, follow_symlinks=False)
        if _directory_identity(current_parent) != expected_parent:
            _fail("foreign-replacement", "candidate parent identity changed")
        descriptor = os.open(output_name, _directory_flags(), dir_fd=parent)
        if (
            _directory_identity(os.fstat(descriptor)) != expected_stage
            or _entry_identity(parent, output_name) != expected_stage
            or _directory_identity(os.stat(parent_path, follow_symlinks=False))
            != expected_parent
        ):
            os.close(descriptor)
            _fail("foreign-replacement", "candidate final identity changed")
        return descriptor

    sealed = validate_candidate_root(stage, final_root_authority=authority)
    if sealed != expected:
        _fail("foreign-replacement", "candidate changed at the final publication boundary")
    return sealed


def _same_candidate_bytes(left: CandidateByteSummary, right: CandidateByteSummary) -> bool:
    return (
        left.candidate_id,
        left.data_release_id,
        left.artifact_count,
        left.artifact_bytes,
        left.manifest_sha256,
    ) == (
        right.candidate_id,
        right.data_release_id,
        right.artifact_count,
        right.artifact_bytes,
        right.manifest_sha256,
    )


def _assemble_candidate_fixture_once(
    receipt_path: Path, output_directory: Path
) -> CandidateAssemblySummary:
    """Assemble, byte-gate, and exclusively promote one complete synthetic candidate."""
    try:
        candidate, fixture_id, expected_manifest, payloads = _load_inputs(receipt_path)
        assembled = copy.deepcopy(candidate)
        manifest_raw, all_payloads = _candidate_bytes(assembled, fixture_id, payloads)
        if _sha256(manifest_raw) != expected_manifest:
            _fail("assembly-output-hash", "generated manifest SHA-256 differs")
    except CandidateAssemblyError:
        raise
    except CandidateContractError as exc:
        raise CandidateAssemblyError(
            "assembly-gate", "candidate template or generated metadata failed validation"
        ) from exc
    output = output_directory
    if output.name in {"", ".", ".."}:
        _fail("assembly-publication", "candidate output path is unsafe")

    promoted = False
    complete = False
    parent_descriptor = -1
    temporary_descriptor = -1
    temporary_identity: tuple[int, int] | None = None
    stage_descriptor = -1
    ownership: _StageOwnership | None = None
    temporary_name = ""
    stage_name: str | None = "candidate"
    parent = output.parent
    stage_paths = [*(artifact["path"] for artifact in assembled["artifacts"]), "manifest.json"]
    try:
        parent, parent_descriptor = _open_trusted_output_parent(output)
        output = parent / output.name
        if _entry_identity(parent_descriptor, output.name) is not None:
            _fail("assembly-publication", "immutable candidate output already exists")
        temporary_name, temporary_descriptor, temporary_identity = _make_staging(parent_descriptor)
        stage_descriptor, stage_identity = _create_owned_directory(
            temporary_descriptor, "candidate", 0o700
        )
        ownership = _StageOwnership(root=stage_identity, directories={}, files={})
        for artifact in assembled["artifacts"]:
            _write_new(
                stage_descriptor,
                artifact["path"],
                all_payloads[artifact["artifactId"]],
                ownership,
            )
        _write_new(stage_descriptor, "manifest.json", manifest_raw, ownership)
        _freeze(stage_descriptor, stage_paths, ownership)
        _fsync_tree(stage_descriptor, stage_paths, ownership)
        _sync_directory(temporary_descriptor)
        gated = validate_candidate_root(stage_descriptor)
        _rename_no_overwrite(
            temporary_descriptor,
            "candidate",
            parent_descriptor,
            output.name,
        )
        promoted = True
        stage_name = None
        os.fchmod(stage_descriptor, 0o555)
        _sync_directory(stage_descriptor)
        _sync_rename_parents(temporary_descriptor, parent_descriptor)
        if not _commit_matches(parent, parent_descriptor, output.name, stage_descriptor):
            _fail("foreign-replacement", "candidate identity changed during publication")
        final = validate_candidate_root(stage_descriptor)
        if not _commit_matches(parent, parent_descriptor, output.name, stage_descriptor):
            _fail("foreign-replacement", "candidate identity changed after validation")
        if not _same_candidate_bytes(final, gated):
            _fail("foreign-replacement", "published candidate differs from the staged gate")
        sealed = _final_publication_gate(
            parent, parent_descriptor, output.name, stage_descriptor, final
        )
        complete = True
        return CandidateAssemblySummary(
            candidate_id=sealed.candidate_id,
            artifact_count=sealed.artifact_count,
            artifact_bytes=sealed.artifact_bytes,
            manifest_sha256=sealed.manifest_sha256,
            output_directory=output,
        )
    except CandidateAssemblyError:
        raise
    except CandidateContractError as exc:
        code = "foreign-replacement" if promoted else "assembly-gate"
        raise CandidateAssemblyError(code, "independent candidate byte gate failed") from exc
    except OSError as exc:
        raise CandidateAssemblyError(
            "assembly-publication", "candidate could not be promoted without overwrite"
        ) from exc
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_failure: CandidateAssemblyError | None = None
        try:
            try:
                if promoted and not complete:
                    if ownership is None:
                        _fail(
                            "assembly-publication",
                            "promoted candidate ownership is unavailable",
                        )
                    stage_name = _rollback_owned_promotion(
                        parent_descriptor,
                        output.name,
                        temporary_descriptor,
                        stage_descriptor,
                        ownership,
                    )
                if temporary_descriptor >= 0 and temporary_identity is not None:
                    _cleanup_staging(
                        parent_descriptor,
                        temporary_name,
                        temporary_descriptor,
                        temporary_identity,
                        stage_descriptor,
                        stage_name,
                        ownership,
                    )
            except CandidateAssemblyError as exc:
                cleanup_failure = exc
            except OSError as exc:
                cleanup_failure = CandidateAssemblyError(
                    "assembly-cleanup", "candidate cleanup could not complete safely"
                )
                cleanup_failure.__cause__ = exc
        finally:
            for descriptor in (stage_descriptor, temporary_descriptor, parent_descriptor):
                if descriptor < 0:
                    continue
                try:
                    os.close(descriptor)
                except OSError as exc:
                    if cleanup_failure is None:
                        cleanup_failure = CandidateAssemblyError(
                            "assembly-cleanup", "candidate descriptors could not be closed"
                        )
                        cleanup_failure.__cause__ = exc
        # Once the final byte/tree pass has linearized a truthful publication,
        # retained private staging and descriptor closure are cleanup-only. A
        # caller must never receive failure for an already committed candidate.
        if cleanup_failure is not None and not complete:
            if isinstance(primary_error, CandidateAssemblyError):
                primary_error.preserve_cleanup_error(cleanup_failure)
            else:
                raise cleanup_failure from primary_error


def assemble_candidate_fixture(
    receipt_path: Path, output_directory: Path
) -> CandidateAssemblySummary:
    """Run one isolated, non-reentrant complete-candidate assembly."""
    if not _ASSEMBLY_LOCK.acquire(blocking=False):
        _fail("assembly-reentrant", "candidate assembly is already active in this process")
    try:
        return _assemble_candidate_fixture_once(receipt_path, output_directory)
    finally:
        _ASSEMBLY_LOCK.release()
