"""Deterministic, immutable assembly of the complete Phase 1 synthetic fixture."""

from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NoReturn

from .byte_gate import validate_candidate_root
from .validator import CandidateContractError, load_candidate_bytes, validate_candidate_document

CONTRACT_ROOT = Path(__file__).resolve().parents[4] / "contracts/candidate-completeness/v1"
_TEMPLATE = CONTRACT_ROOT / "fixtures/valid/engineering-candidate.json"
_PRE_GATE_COUNT = 50
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
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


def _read_bound_receipt(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > _MAX_RECEIPT_BYTES
        ):
            _fail("assembly-receipt", "receipt must be one bounded regular file")
        raw = bytearray()
        while len(raw) < before.st_size:
            chunk = os.read(descriptor, before.st_size - len(raw))
            if not chunk:
                _fail("assembly-receipt", "receipt ended while it was read")
            raw.extend(chunk)
        if os.read(descriptor, 1) or _identity(os.fstat(descriptor)) != _identity(before):
            _fail("assembly-receipt", "receipt changed while it was read")
        return bytes(raw)
    except CandidateAssemblyError:
        raise
    except OSError as exc:
        raise CandidateAssemblyError("assembly-receipt", "receipt cannot be opened safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


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

    template_raw = _TEMPLATE.read_bytes()
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
    for entry, artifact in zip(entries, required, strict=True):
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


def _write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _freeze(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        os.chmod(path, 0o555 if path.is_dir() else 0o444, follow_symlinks=False)
    # macOS RENAME_EXCL requires write permission on the moved directory.
    # The held descriptor removes it immediately after exclusive promotion.
    os.chmod(root, 0o755)


def _thaw(root: Path) -> None:
    if not root.exists():
        return
    os.chmod(root, 0o700)
    for path in root.rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600, follow_symlinks=False)


def _fsync_tree(root: Path) -> None:
    directories = [root, *(path for path in root.rglob("*") if path.is_dir())]
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


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

    temporary = Path(tempfile.mkdtemp(prefix=".candidate-assembly-", dir=parent))
    stage = temporary / "candidate"
    stage.mkdir()
    promoted = False
    parent_descriptor = -1
    temporary_descriptor = -1
    stage_descriptor = -1
    try:
        for artifact in assembled["artifacts"]:
            _write_new(stage / artifact["path"], all_payloads[artifact["artifactId"]])
        _write_new(stage / "manifest.json", manifest_raw)
        _freeze(stage)
        _fsync_tree(stage)
        stage_descriptor = os.open(
            stage,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0),
        )
        gated = validate_candidate_root(stage)
        parent_descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0),
        )
        temporary_descriptor = os.open(
            temporary,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0),
        )
        _rename_no_overwrite(
            temporary_descriptor,
            "candidate",
            parent_descriptor,
            output.name,
        )
        promoted = True
        os.fchmod(stage_descriptor, 0o555)
        os.fsync(stage_descriptor)
        before = os.fstat(stage_descriptor)
        os.fsync(parent_descriptor)
        current = os.stat(output.name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            _fail("foreign-replacement", "candidate identity changed during publication")
        final = validate_candidate_root(output)
        current = os.stat(output.name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            _fail("foreign-replacement", "candidate identity changed after validation")
        if final != gated:
            _fail("foreign-replacement", "published candidate differs from the staged gate")
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
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
        if temporary_descriptor >= 0:
            os.close(temporary_descriptor)
        if stage_descriptor >= 0:
            os.close(stage_descriptor)
        if not promoted:
            _thaw(stage)
        shutil.rmtree(temporary, ignore_errors=False)
