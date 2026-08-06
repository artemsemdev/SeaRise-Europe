"""Test the protected Phase 0R owner-promotion boundary."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import zipfile
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


class MockGitHubApi:
    def __init__(
        self,
        source_revision: str,
        evidence_revision: str,
        *,
        master_revision: str | None = None,
        candidate: Path | None = None,
        mac_candidate: Path | None = None,
        linux_binding: dict[str, object] | None = None,
        mac_binding: dict[str, object] | None = None,
        run_id: int = 101,
        pr_number: int = 202,
    ):
        workflow_id = 303
        artifact_ids = {"linux": 404, "macos": 405}
        repository_id = 606
        jobs_path = (
            f"/repos/{owner_promotion.REPOSITORY}/actions/runs/{run_id}/"
            "attempts/1/jobs?per_page=100"
        )
        master_revision = master_revision or evidence_revision
        candidates = {"linux": candidate, "macos": mac_candidate or candidate}
        bindings = {"linux": linux_binding, "macos": mac_binding}
        self.artifacts = {
            platform: self._artifact_bytes(observed, platform, bindings[platform])
            for platform, observed in candidates.items()
        }
        self.responses = {
            f"/repos/{owner_promotion.REPOSITORY}/actions/runs/{run_id}": {
                "id": run_id,
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
                "head_sha": source_revision,
                "head_branch": "master",
                "path": owner_promotion.VALIDATION_WORKFLOW,
                "repository": {
                    "id": repository_id,
                    "full_name": owner_promotion.REPOSITORY,
                },
                "head_repository": {
                    "id": repository_id,
                    "full_name": owner_promotion.REPOSITORY,
                },
                "actor": {"login": owner_promotion.OWNER_LOGIN},
                "triggering_actor": {"login": owner_promotion.OWNER_LOGIN},
                "workflow_id": workflow_id,
                "run_attempt": 1,
            },
            f"/repos/{owner_promotion.REPOSITORY}/actions/workflows/{workflow_id}": {
                "path": owner_promotion.VALIDATION_WORKFLOW,
                "name": owner_promotion.VALIDATION_WORKFLOW_NAME,
                "state": "active",
            },
            jobs_path: {
                "total_count": 2,
                "jobs": [
                    {
                        "id": 501,
                        "name": owner_promotion.VALIDATION_JOB_NAME,
                        "run_id": run_id,
                        "head_sha": source_revision,
                        "status": "completed",
                        "conclusion": "success",
                    },
                    {
                        "id": 502,
                        "name": owner_promotion.MAC_VALIDATION_JOB_NAME,
                        "run_id": run_id,
                        "head_sha": source_revision,
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            },
            f"/repos/{owner_promotion.REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100": {
                "total_count": 2,
                "artifacts": [
                    {
                        "id": artifact_ids["linux"],
                        "name": f"ar6-linux-candidate-{source_revision}-{run_id}",
                        "expired": False,
                        "size_in_bytes": len(self.artifacts["linux"]),
                        "digest": f"sha256:{hashlib.sha256(self.artifacts['linux']).hexdigest()}",
                        "workflow_run": {
                            "id": run_id,
                            "repository_id": repository_id,
                            "head_repository_id": repository_id,
                            "head_branch": "master",
                            "head_sha": source_revision,
                        },
                    },
                    {
                        "id": artifact_ids["macos"],
                        "name": f"ar6-macos-arm64-candidate-{source_revision}-{run_id}",
                        "expired": False,
                        "size_in_bytes": len(self.artifacts["macos"]),
                        "digest": f"sha256:{hashlib.sha256(self.artifacts['macos']).hexdigest()}",
                        "workflow_run": {
                            "id": run_id,
                            "repository_id": repository_id,
                            "head_repository_id": repository_id,
                            "head_branch": "master",
                            "head_sha": source_revision,
                        },
                    },
                ],
            },
            (
                f"/repos/{owner_promotion.REPOSITORY}/actions/workflows/"
                "phase-0r-owner-promotion.yml/runs"
                "?event=workflow_dispatch&per_page=100"
            ): {"total_count": 0, "workflow_runs": []},
            f"/repos/{owner_promotion.REPOSITORY}/pulls/{pr_number}": {
                "number": pr_number,
                "state": "closed",
                "merged": True,
                "base": {
                    "ref": "master",
                    "sha": source_revision,
                    "repo": {"full_name": owner_promotion.REPOSITORY},
                },
                "head": {
                    "sha": evidence_revision,
                    "repo": {"full_name": owner_promotion.REPOSITORY},
                },
                "merge_commit_sha": master_revision,
            },
            f"/repos/{owner_promotion.REPOSITORY}/pulls/201": {
                "number": 201,
                "state": "closed",
                "merged": True,
                "base": {
                    "ref": "master",
                    "repo": {"full_name": owner_promotion.REPOSITORY},
                },
                "head": {
                    "sha": source_revision,
                    "repo": {"full_name": owner_promotion.REPOSITORY},
                },
                "merge_commit_sha": source_revision,
            },
            f"/repos/{owner_promotion.REPOSITORY}/commits/master": {"sha": master_revision},
            (
                f"/repos/{owner_promotion.REPOSITORY}/compare/"
                f"{source_revision}...{evidence_revision}"
            ): {
                "status": "ahead",
                "merge_base_commit": {"sha": source_revision},
            },
            (
                f"/repos/{owner_promotion.REPOSITORY}/compare/{master_revision}...{master_revision}"
            ): {
                "status": "identical",
                "merge_base_commit": {"sha": master_revision},
            },
        }
        self.artifact_paths = {
            f"/repos/{owner_promotion.REPOSITORY}/actions/artifacts/{artifact_id}/zip": platform
            for platform, artifact_id in artifact_ids.items()
        }

    @staticmethod
    def _artifact_bytes(
        candidate: Path | None,
        platform: str,
        binding: dict[str, object] | None,
    ) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as bundle:
            if candidate is None:
                bundle.writestr(
                    f"{owner_promotion.LINUX_CANDIDATE_DIRECTORY}/placeholder",
                    "validated by the candidate-binding oracle",
                )
            else:
                for candidate_file in sorted(candidate.rglob("*")):
                    if candidate_file.is_file():
                        bundle.write(
                            candidate_file,
                            (
                                f"{owner_promotion.LINUX_CANDIDATE_DIRECTORY}/"
                                f"{candidate_file.relative_to(candidate).as_posix()}"
                            ),
                        )
            timing_name = (
                "build-timing-linux.json"
                if platform == "linux"
                else "build-timing-macos-arm64.json"
            )
            bundle.writestr(timing_name, _timing_bytes(binding or {}))
            if platform == "macos":
                bundle.writestr("browser-trace-macos-arm64.json", _trace_bytes())
        return stream.getvalue()

    def get_json(self, path: str):
        return self.responses[path]

    def download(self, path: str, destination: Path) -> None:
        destination.write_bytes(self.artifacts[self.artifact_paths[path]])


class FakeHttpResponse:
    def __init__(
        self,
        status: int,
        url: str,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._status = status
        self._url = url
        self._body = io.BytesIO(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def getcode(self) -> int:
        return self._status

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)
