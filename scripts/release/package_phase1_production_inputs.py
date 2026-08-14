#!/usr/bin/env python3
"""Create a deterministic, reviewable Phase 1 production-input archive."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "contracts/candidate-completeness/v2/required-artifacts.json"
PRE_GATE_COUNT = 51
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_BUNDLE_BYTES = 8 * 1024 * 1024 * 1024
TOOLCHAIN_FILES = (
    "brotli",
    "go-pmtiles_1.31.2_Linux_x86_64.tar.gz",
    "pmtiles",
    "tippecanoe",
    "tippecanoe-2.79.0.tar.gz",
    "tippecanoe-decode",
)


class InputBundleError(ValueError):
    """The reviewed production inputs cannot be packaged safely."""


@dataclass(frozen=True)
class InputFile:
    source: Path
    archive_path: str
    byte_size: int
    sha256: str
    executable: bool = False


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _hash_file(path: Path, *, archive_path: str, executable: bool = False) -> InputFile:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise InputBundleError(f"cannot open reviewed input: {archive_path}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise InputBundleError(f"reviewed input is not a non-empty regular file: {archive_path}")
        if before.st_size > MAX_FILE_BYTES:
            raise InputBundleError(f"reviewed input exceeds the per-file limit: {archive_path}")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise InputBundleError(f"reviewed input changed while hashing: {archive_path}")
        return InputFile(path, archive_path, before.st_size, digest.hexdigest(), executable)
    finally:
        os.close(descriptor)


def _candidate_paths() -> tuple[str, ...]:
    document = json.loads(INVENTORY.read_text(encoding="utf-8"))
    return tuple(item["path"] for item in document["requiredArtifacts"][:PRE_GATE_COUNT])


def _files(args: argparse.Namespace) -> tuple[InputFile, ...]:
    expected = _candidate_paths()
    observed = {
        path.relative_to(args.candidate_input_root).as_posix()
        for path in args.candidate_input_root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if observed != set(expected):
        raise InputBundleError("candidate input root must contain exactly 51 pre-gate paths")
    specifications = [
        (args.candidate_input_root / path, f"candidate-inputs/{path}", False)
        for path in expected
    ]
    specifications.extend(
        [
            (
                args.spatial_receipt,
                "authorities/geonames-spatial-stage-v1.receipt.json",
                False,
            ),
            (
                args.settlement_artifact_receipt,
                "authorities/settlements.receipt.json",
                False,
            ),
            (
                args.browser_performance,
                "evidence/browser-worker-performance.chromium.json",
                False,
            ),
            (args.performance_queries, "evidence/performance-queries.json", False),
        ]
    )
    specifications.extend(
        (
            args.toolchain_root / name,
            f"toolchain/{name}",
            name in {"brotli", "pmtiles", "tippecanoe", "tippecanoe-decode"},
        )
        for name in TOOLCHAIN_FILES
    )
    files = tuple(
        _hash_file(source, archive_path=archive_path, executable=executable)
        for source, archive_path, executable in specifications
    )
    if sum(item.byte_size for item in files) > MAX_BUNDLE_BYTES:
        raise InputBundleError("reviewed input bundle exceeds the total size limit")
    return files


def _tar_info(path: str, size: int, *, executable: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(path)
    info.size = size
    info.mode = 0o555 if executable else 0o444
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _copy_verified(archive: tarfile.TarFile, item: InputFile) -> None:
    with item.source.open("rb") as stream:
        raw = stream.read()
    if len(raw) != item.byte_size or hashlib.sha256(raw).hexdigest() != item.sha256:
        raise InputBundleError(f"reviewed input changed before packaging: {item.archive_path}")
    archive.addfile(
        _tar_info(item.archive_path, len(raw), executable=item.executable),
        io.BytesIO(raw),
    )


def package_inputs(args: argparse.Namespace) -> dict[str, object]:
    files = _files(args)
    manifest = {
        "schemaVersion": 1,
        "bundleType": "phase-1-production-inputs",
        "candidateInputCount": PRE_GATE_COUNT,
        "files": [
            {
                "path": item.archive_path,
                "byteSize": item.byte_size,
                "sha256": item.sha256,
                "mode": "0555" if item.executable else "0444",
            }
            for item in sorted(files, key=lambda value: value.archive_path)
        ],
    }
    manifest_raw = _canonical(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    complete = False
    try:
        with os.fdopen(descriptor, "wb") as output:
            with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                authority_written = False
                for item in sorted(files, key=lambda value: value.archive_path):
                    if not authority_written and item.archive_path > "input-authority.json":
                        archive.addfile(
                            _tar_info("input-authority.json", len(manifest_raw)),
                            io.BytesIO(manifest_raw),
                        )
                        authority_written = True
                    _copy_verified(archive, item)
                if not authority_written:
                    archive.addfile(
                        _tar_info("input-authority.json", len(manifest_raw)),
                        io.BytesIO(manifest_raw),
                    )
            output.flush()
            os.fsync(output.fileno())
        complete = True
    finally:
        if not complete:
            args.output.unlink(missing_ok=True)
    return {
        "archive": str(args.output),
        "byteSize": args.output.stat().st_size,
        "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "fileCount": len(files) + 1,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-input-root", type=Path, required=True)
    parser.add_argument("--spatial-receipt", type=Path, required=True)
    parser.add_argument("--settlement-artifact-receipt", type=Path, required=True)
    parser.add_argument("--browser-performance", type=Path, required=True)
    parser.add_argument("--performance-queries", type=Path, required=True)
    parser.add_argument("--toolchain-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    try:
        print(json.dumps(package_inputs(_parser().parse_args()), sort_keys=True))
    except (InputBundleError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"phase-1 production input packaging failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
