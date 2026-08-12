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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, NoReturn

from .byte_gate import validate_candidate_root
from .validator import CandidateContractError, load_candidate_bytes, validate_candidate_document

CONTRACT_ROOT = Path(__file__).resolve().parents[4] / "contracts/candidate-completeness/v1"
_TEMPLATE = CONTRACT_ROOT / "fixtures/valid/engineering-candidate.json"
_PRE_GATE_COUNT = 50
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


class CandidateAssemblyError(ValueError):
    """The synthetic candidate could not be assembled without broadening claims."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


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


def _read_bound_receipt(path: Path) -> bytes:
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
        _fail("assembly-inputs", "receipt must contain exactly 50 pre-gate inputs")
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


def _gate_reports(candidate: Mapping[str, Any], fixture_id: str) -> tuple[bytes, bytes]:
    report = {
        "schemaVersion": 1,
        "candidateId": candidate["candidateId"],
        "fixtureId": fixture_id,
        "decision": "synthetic-fixture-pass",
        "inputCount": _PRE_GATE_COUNT,
        "claims": _CLAIMS,
    }
    json_raw = _canonical(report)
    markdown = (
        "# Synthetic Phase 1 gate report\n\n"
        f"- Candidate: `{candidate['candidateId']}`\n"
        f"- Fixture: `{fixture_id}`\n"
        "- Decision: synthetic fixture pass\n"
        "- Production: false\n"
        "- Publication: false\n"
        "- Scientific approval: false\n"
        "- Format validity: false\n"
    ).encode("utf-8")
    return json_raw, markdown


def _candidate_bytes(
    candidate: dict[str, Any], fixture_id: str, payloads: dict[str, bytes]
) -> tuple[bytes, dict[str, bytes]]:
    report_json, report_markdown = _gate_reports(candidate, fixture_id)
    payloads = {
        **payloads,
        "release-gate-report-json": report_json,
        "release-gate-report-markdown": report_markdown,
    }
    artifacts = candidate["artifacts"]
    for artifact in artifacts[:52]:
        raw = payloads[artifact["artifactId"]]
        artifact.update(byteSize=len(raw), sha256=_sha256(raw))
    subjects = sorted(
        ({"path": item["path"], "sha256": item["sha256"]} for item in artifacts[:52]),
        key=lambda item: item["path"],
    )
    candidate["checksumInventory"]["subjects"] = subjects
    checksums = "".join(f"{item['sha256']}  {item['path']}\n" for item in subjects).encode()
    artifacts[52].update(byteSize=len(checksums), sha256=_sha256(checksums))
    payloads["checksums"] = checksums
    validate_candidate_document(candidate)
    return _canonical(candidate), payloads


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _directory_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


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


def _open_or_create_directory(parent: int, parts: Iterable[str]) -> int:
    descriptor = os.dup(parent)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o755, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError:
        os.close(descriptor)
        raise


def _logical(path: str) -> PurePosixPath:
    logical = PurePosixPath(path)
    if logical.is_absolute() or any(part in {"", ".", ".."} for part in logical.parts):
        _fail("assembly-publication", "candidate artifact path is unsafe")
    return logical


def _write_new(root: int, path: str, raw: bytes) -> None:
    """Create one stage file through the held stage-root descriptor."""
    logical = _logical(path)
    parent = _open_or_create_directory(root, logical.parts[:-1])
    descriptor = -1
    try:
        descriptor = os.open(
            logical.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)


def _stage_directories(paths: Iterable[str]) -> list[PurePosixPath]:
    return sorted(
        {PurePosixPath(part) for path in paths for part in _logical(path).parents if part.parts},
        key=lambda item: (len(item.parts), item.as_posix()),
        reverse=True,
    )


def _chmod_file(root: int, path: str, mode: int) -> None:
    logical = _logical(path)
    parent = _open_directory(root, logical.parts[:-1])
    descriptor = -1
    try:
        descriptor = os.open(
            logical.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
        os.fchmod(descriptor, mode)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)


def _freeze(root: int, paths: Iterable[str]) -> None:
    paths = tuple(paths)
    for path in paths:
        _chmod_file(root, path, 0o444)
    for directory_path in _stage_directories(paths):
        descriptor = _open_directory(root, directory_path.parts)
        try:
            os.fchmod(descriptor, 0o555)
        finally:
            os.close(descriptor)
    # Darwin RENAME_EXCL needs the moved directory to remain writable. Its
    # descriptor is frozen immediately after promotion.
    os.fchmod(root, 0o755)


def _thaw(root: int, paths: Iterable[str]) -> None:
    os.fchmod(root, 0o700)
    for directory_path in _stage_directories(paths):
        descriptor = _open_directory(root, directory_path.parts)
        try:
            os.fchmod(descriptor, 0o700)
        finally:
            os.close(descriptor)


def _sync_directory(descriptor: int) -> None:
    os.fsync(descriptor)


def _fsync_tree(root: int, paths: Iterable[str]) -> None:
    """Synchronize child directories before their parents through held descriptors."""
    for directory_path in _stage_directories(paths):
        descriptor = _open_directory(root, directory_path.parts)
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


def _make_staging(parent: int) -> tuple[str, int]:
    for _ in range(32):
        name = f".candidate-assembly-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            continue
        try:
            return name, os.open(name, _directory_flags(), dir_fd=parent)
        except OSError:
            os.rmdir(name, dir_fd=parent)
            raise
    _fail("assembly-publication", "cannot reserve a private staging directory")


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


def _remove_known_stage(root: int, paths: Iterable[str]) -> None:
    paths = tuple(paths)
    _thaw(root, paths)
    for path in paths:
        logical = _logical(path)
        parent = _open_directory(root, logical.parts[:-1])
        try:
            os.unlink(logical.name, dir_fd=parent)
        finally:
            os.close(parent)
    for directory_path in _stage_directories(paths):
        parent = _open_directory(root, directory_path.parts[:-1])
        try:
            os.rmdir(directory_path.name, dir_fd=parent)
        finally:
            os.close(parent)


def _cleanup_staging(
    parent: int,
    temporary_name: str,
    temporary: int,
    stage: int,
    paths: Iterable[str],
) -> None:
    """Remove only the held staging tree; a replacement is intentionally retained."""
    stage_identity = _directory_identity(os.fstat(stage))
    if _entry_matches(temporary, "candidate", stage_identity):
        _remove_known_stage(stage, paths)
        if _entry_matches(temporary, "candidate", stage_identity):
            os.rmdir("candidate", dir_fd=temporary)
    temporary_identity = _directory_identity(os.fstat(temporary))
    if _entry_matches(parent, temporary_name, temporary_identity):
        os.rmdir(temporary_name, dir_fd=parent)


def _rollback_owned_promotion(
    parent: int,
    output_name: str,
    temporary: int,
    stage: int,
) -> None:
    """Durably move our promoted inode away without touching a foreign final directory."""
    if not _entry_matches(parent, output_name, _directory_identity(os.fstat(stage))):
        return
    os.fchmod(stage, 0o755)
    _rename_no_overwrite(parent, output_name, temporary, "candidate")
    _sync_rename_parents(parent, temporary)


def assemble_candidate_fixture(
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
    output = output_directory.absolute()
    if output.name in {"", ".", ".."}:
        _fail("assembly-publication", "candidate output path is unsafe")
    try:
        parent = output.parent.resolve(strict=True)
    except OSError as exc:
        raise CandidateAssemblyError(
            "assembly-publication", "output parent is unavailable"
        ) from exc
    if not parent.is_dir() or output.parent.is_symlink():
        _fail("assembly-publication", "candidate output parent is unsafe")
    output = parent / output.name
    if os.path.lexists(output):
        _fail("assembly-publication", "immutable candidate output already exists")

    promoted = False
    complete = False
    parent_descriptor = -1
    temporary_descriptor = -1
    stage_descriptor = -1
    temporary_name = ""
    stage_paths = [*(artifact["path"] for artifact in assembled["artifacts"]), "manifest.json"]
    try:
        parent_descriptor = os.open(parent, _directory_flags())
        temporary_name, temporary_descriptor = _make_staging(parent_descriptor)
        os.mkdir("candidate", 0o700, dir_fd=temporary_descriptor)
        stage_descriptor = os.open("candidate", _directory_flags(), dir_fd=temporary_descriptor)
        for artifact in assembled["artifacts"]:
            _write_new(stage_descriptor, artifact["path"], all_payloads[artifact["artifactId"]])
        _write_new(stage_descriptor, "manifest.json", manifest_raw)
        _freeze(stage_descriptor, stage_paths)
        _fsync_tree(stage_descriptor, stage_paths)
        _sync_directory(temporary_descriptor)
        gated = validate_candidate_root(stage_descriptor)
        _rename_no_overwrite(
            temporary_descriptor,
            "candidate",
            parent_descriptor,
            output.name,
        )
        promoted = True
        os.fchmod(stage_descriptor, 0o555)
        _sync_directory(stage_descriptor)
        _sync_rename_parents(temporary_descriptor, parent_descriptor)
        if not _commit_matches(parent, parent_descriptor, output.name, stage_descriptor):
            _fail("foreign-replacement", "candidate identity changed during publication")
        final = validate_candidate_root(stage_descriptor)
        if not _commit_matches(parent, parent_descriptor, output.name, stage_descriptor):
            _fail("foreign-replacement", "candidate identity changed after validation")
        if final != gated:
            _fail("foreign-replacement", "published candidate differs from the staged gate")
        complete = True
        return CandidateAssemblySummary(
            candidate_id=final.candidate_id,
            artifact_count=final.artifact_count,
            artifact_bytes=final.artifact_bytes,
            manifest_sha256=final.manifest_sha256,
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
        try:
            if promoted and not complete:
                _rollback_owned_promotion(
                    parent_descriptor,
                    output.name,
                    temporary_descriptor,
                    stage_descriptor,
                )
            if not complete and temporary_descriptor >= 0:
                _cleanup_staging(
                    parent_descriptor,
                    temporary_name,
                    temporary_descriptor,
                    stage_descriptor,
                    stage_paths,
                )
            elif complete and temporary_descriptor >= 0:
                _cleanup_staging(
                    parent_descriptor,
                    temporary_name,
                    temporary_descriptor,
                    stage_descriptor,
                    (),
                )
        finally:
            if stage_descriptor >= 0:
                os.close(stage_descriptor)
            if temporary_descriptor >= 0:
                os.close(temporary_descriptor)
            if parent_descriptor >= 0:
                os.close(parent_descriptor)
