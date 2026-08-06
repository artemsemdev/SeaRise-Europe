"""Test the protected Phase 0R owner-promotion boundary."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import searise_pipeline.release.owner_promotion as owner_promotion

REPOSITORY_ROOT = Path(__file__).parents[4]


def _load_cli():
    path = REPOSITORY_ROOT / "scripts/science/promote_phase_0r_release.py"
    spec = importlib.util.spec_from_file_location("phase_0r_owner_promotion_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load owner promotion CLI from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _head() -> str:
    return subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _evidence_repository(
    tmp_path: Path,
    *,
    extra_path: str | None = None,
    deleted_path: str | None = None,
    symlink_path: str | None = None,
    submodule_path: str | None = None,
    reverted_path: str | None = None,
) -> tuple[Path, str, str, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "symbolic-ref", "HEAD", "refs/heads/master")
    (repository / "source.txt").write_text("candidate source\n", encoding="utf-8")
    if deleted_path is not None:
        deleted = repository / deleted_path
        deleted.parent.mkdir(parents=True, exist_ok=True)
        deleted.write_text("present at source revision\n", encoding="utf-8")
    _git(repository, "add", "source.txt")
    if deleted_path is not None:
        _git(repository, "add", deleted_path)
    _git(repository, "commit", "-m", "test: candidate source")
    source_revision = _git(repository, "rev-parse", "HEAD")
    _git(repository, "checkout", "-b", "evidence")

    if reverted_path is not None:
        reverted = repository / reverted_path
        reverted.parent.mkdir(parents=True, exist_ok=True)
        reverted.write_text("temporarily changed after build\n", encoding="utf-8")
        _git(repository, "add", reverted_path)
        _git(repository, "commit", "-m", "feat: hidden post-build change")
        reverted.unlink()

    for relative in owner_promotion._REQUIRED_EVIDENCE_DELTA:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"evidence for {relative}\n", encoding="utf-8")
    if extra_path is not None:
        extra = repository / extra_path
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("forbidden post-build change\n", encoding="utf-8")
    if deleted_path is not None:
        (repository / deleted_path).unlink()
    if symlink_path is not None:
        link = repository / symlink_path
        link.unlink()
        link.symlink_to("source.txt")
    _git(repository, "add", "-A")
    if submodule_path is not None:
        target = repository / submodule_path
        target.unlink()
        _git(
            repository,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{source_revision},{submodule_path}",
        )
    _git(repository, "commit", "-m", "docs: commit final release evidence")
    evidence_revision = _git(repository, "rev-parse", "HEAD")
    _git(repository, "checkout", "master")
    _git(repository, "merge", "--no-ff", "--no-edit", "evidence")
    return repository, source_revision, evidence_revision, _git(
        repository, "rev-parse", "HEAD"
    )


def _context(source_revision: str) -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": owner_promotion.REPOSITORY,
        "GITHUB_REF": owner_promotion.MASTER_REF,
        "GITHUB_ACTOR": owner_promotion.OWNER_LOGIN,
        "GITHUB_TRIGGERING_ACTOR": owner_promotion.OWNER_LOGIN,
        "GITHUB_WORKFLOW": "Phase 0R owner promotion",
        "GITHUB_WORKFLOW_REF": (
            f"{owner_promotion.REPOSITORY}/{owner_promotion.OWNER_WORKFLOW}"
            f"@{owner_promotion.MASTER_REF}"
        ),
        "SEARISE_OWNER_ENVIRONMENT": owner_promotion.OWNER_ENVIRONMENT,
        "GITHUB_SHA": source_revision,
        "GITHUB_RUN_ID": "9001",
        "GITHUB_RUN_ATTEMPT": "1",
    }


def _timing_document(binding: dict[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "candidate": binding,
        "timer": "python-time-perf-counter",
        "startedBeforeSourceVerification": True,
        "endedAfterAtomicCandidatePublish": True,
        "fullCleanBuildDurationSeconds": 10,
    }


def _timing_bytes(binding: dict[str, object]) -> bytes:
    return (json.dumps(_timing_document(binding), sort_keys=True) + "\n").encode("utf-8")


def _trace_bytes() -> bytes:
    return b'{"trusted":"macos-browser-trace"}\n'


def _committed_delivery(binding: dict[str, object]) -> dict[str, object]:
    return {
        "trace": {
            "path": "browser-trace-macos-arm64.json",
            "sha256": hashlib.sha256(_trace_bytes()).hexdigest(),
        },
        "buildTiming": {
            "path": "build-timing-macos-arm64.json",
            "sha256": hashlib.sha256(_timing_bytes(binding)).hexdigest(),
        },
        "fullCleanBuildDurationSeconds": 10.0,
    }
