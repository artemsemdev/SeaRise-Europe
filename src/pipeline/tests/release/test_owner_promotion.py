"""Test the protected Phase 0R owner-promotion boundary."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

import searise_pipeline.release.owner_promotion as owner_promotion
from searise_pipeline.release import create_delivery_report
from searise_pipeline.release.evidence import binding_sha256, sha256
from searise_pipeline.science import ScienceContractError

from .test_evidence import _candidate, _seal
from .test_recovery_gate import BUILD_CHECKS, _finalize, _promotion_inputs

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
    _git(repository, "config", "user.name", "Artem")
    _git(
        repository,
        "config",
        "user.email",
        "6793222+artemsemdev@users.noreply.github.com",
    )
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


def _synthetic_binding(
    release: dict[str, object],
    source_revision: str,
    environment: dict[str, object],
) -> dict[str, object]:
    artifact_hashes = {f"artifact-{index:02d}": "a" * 64 for index in range(31)}
    vector = environment["vector"]
    python = environment["python"]
    return {
        "releaseId": "phase-0r-ar6-v1",
        "releaseContractId": release["releaseContractId"],
        "manifestSha256": "b" * 64,
        "buildReceiptSha256": "c" * 64,
        "buildEvidenceSha256": "d" * 64,
        "sourceReceiptSha256": "e" * 64,
        "artifactHashes": artifact_hashes,
        "candidateFileHashes": artifact_hashes,
        "sourceRevision": source_revision,
        "environmentIdentity": environment,
        "validatedEnvironmentProfile": {
            "pythonPlatform": python["platform"],
            "pythonLockSha256": python["lock_sha256"],
            "vectorPlatform": vector["pmtiles_distribution_platform"],
            "tippecanoeBinarySha256": vector["tippecanoe_binary_sha256"],
        },
    }


def _reproducibility_report(
    release: dict[str, object],
    mac: dict[str, object],
    linux: dict[str, object],
) -> dict[str, object]:
    candidates = [mac, linux]
    profiles = sorted(
        {tuple(item["validatedEnvironmentProfile"].items()) for item in candidates}
    )
    required = [
        {
            "candidateBindingSha256": binding_sha256(item),
            "releaseId": item["releaseId"],
            "sourceRevision": item["sourceRevision"],
            "receiptBuildRunId": item["environmentIdentity"]["buildRunId"],
            "validatedEnvironmentProfile": item["validatedEnvironmentProfile"],
        }
        for item in candidates
    ]
    minimum = release["reproducibility"]["minimumIndependentEnvironments"]
    return {
        "schemaVersion": 1,
        "status": "pending-external-provenance",
        "localComparisonStatus": "passed",
        "externalProvenanceStatus": "required",
        "candidates": candidates,
        "environments": [item["environmentIdentity"] for item in candidates],
        "independentEnvironmentCount": 0,
        "receiptProfileCount": len(profiles),
        "receiptProfiles": [dict(profile) for profile in profiles],
        "requiredExternalBindings": required,
        "externalProvenanceRequirement": {
            "provider": "github-actions",
            "candidateBindingRequired": True,
            "distinctTrustedRunCount": minimum,
            "distinctValidatedProfileCount": minimum,
            "receiptProfilesAreProof": False,
        },
        "maximumScientificValueDifferenceMillimetres": 0,
        "validIdSetDifference": 0,
        "byteIdentityWithinPinnedToolchain": True,
        "comparedArtifactCount": 31,
        "comparisonDurationSeconds": 1.0,
    }


def _promotion_evidence(source_revision: str):
    release = json.loads(
        (REPOSITORY_ROOT / owner_promotion.CONTRACT_PATH).read_text(encoding="utf-8")
    )
    mac = _synthetic_binding(
        release,
        source_revision,
        _pinned_environment(
            release,
            platform="macos-arm64-cp39",
            vector_platform="darwin-arm64",
            build_run_id="github-101-1-macos-arm64",
        ),
    )
    linux = _synthetic_binding(
        release,
        source_revision,
        _pinned_environment(
            release,
            platform="linux-x86_64-cp311",
            vector_platform="linux-x86_64",
            build_run_id="github-101-1-linux-x86_64",
        ),
    )
    report = _reproducibility_report(release, mac, linux)
    gate = {
        "schemaVersion": 1,
        "gateId": "phase-0r-ar6-regional-release-v1",
        "automatedValidation": "pending",
        "releaseDisposition": "pending-owner",
        "phase1Unlocked": False,
        "checks": {**BUILD_CHECKS, "crossEnvironmentReproducibility": False},
        "blockingChecks": ["crossEnvironmentReproducibility"],
        "fallback": "do-not-publish-or-unlock-phase-1",
        "externalVerificationRequired": {
            "reproducibilityProvenance": {
                "status": "pending-external-verification",
                "provider": "github-actions",
                "requiredExternalBindings": report["requiredExternalBindings"],
            }
        },
    }
    evidence_hashes = {
        "candidate-binding.json": "1" * 64,
        "build-receipt.json": "2" * 64,
        "build-timing-macos-arm64.json": hashlib.sha256(_timing_bytes(mac)).hexdigest(),
        "browser-trace-macos-arm64.json": hashlib.sha256(_trace_bytes()).hexdigest(),
        "delivery-report.json": "3" * 64,
        "reproducibility-report.json": "4" * 64,
        "automated-gate.json": "5" * 64,
        "checksums.txt": "6" * 64,
    }
    return mac, linux, report, gate, evidence_hashes, _committed_delivery(mac)


def _candidate_oracle(mac: dict[str, object], linux: dict[str, object]):
    def binding(candidate: Path, *, contract: dict[str, object]):
        del contract
        return mac if "macos-extracted" in candidate.parts else linux

    return binding


def _pinned_environment(
    release: dict[str, object],
    *,
    platform: str,
    vector_platform: str,
    build_run_id: str,
) -> dict[str, object]:
    toolchain = release["toolchain"]
    python = toolchain["python"]
    tippecanoe = toolchain["tippecanoe"]
    pmtiles = toolchain["pmtiles"]
    profile = python["profiles"][platform]
    reference = tippecanoe["referenceBuilds"][vector_platform]
    asset = pmtiles["assets"][vector_platform]
    return {
        "buildRunId": build_run_id,
        "python": {
            "platform": platform,
            "python_version": profile["pythonVersion"],
            "lock_path": profile["lockPath"],
            "lock_sha256": profile["lockSha256"],
            "packages": python["packageVersions"],
            "gdal_version": profile["gdal"],
            "rasterio_proj_version": profile["rasterioProj"],
            "pyproj_proj_version": profile["pyprojProj"],
        },
        "vector": {
            "tippecanoe_version": tippecanoe["version"],
            "tippecanoe_source_sha256": tippecanoe["sourceSha256"],
            "tippecanoe_binary_sha256": reference["tippecanoeBinarySha256"],
            "pmtiles_version": pmtiles["version"],
            "pmtiles_commit": pmtiles["commit"],
            "pmtiles_distribution_platform": vector_platform,
            "pmtiles_distribution_sha256": asset["sha256"],
            "decode_binary_sha256": reference["decodeBinarySha256"],
        },
    }


def _write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")


def _committed_bundle(repository_root: Path, source_revision: str) -> Path:
    root = repository_root / owner_promotion.MAC_EVIDENCE_ROOT
    root.mkdir(parents=True)
    receipt = {
        "releaseId": "phase-0r-ar6-v1",
        "sourceRevision": source_revision,
        "environmentIdentity": {"buildRunId": "local-mac-build"},
    }
    _write_json(root / "build-receipt.json", receipt)
    binding = {
        "releaseId": receipt["releaseId"],
        "sourceRevision": source_revision,
        "environmentIdentity": receipt["environmentIdentity"],
        "manifestSha256": "a" * 64,
        "buildReceiptSha256": sha256(root / "build-receipt.json"),
    }
    _write_json(root / "candidate-binding.json", binding)
    (root / "build-timing-macos-arm64.json").write_bytes(_timing_bytes(binding))
    (root / "browser-trace-macos-arm64.json").write_bytes(_trace_bytes())
    delivery = {
        "status": "passed",
        "trace": {
            "path": "browser-trace-macos-arm64.json",
            "sha256": sha256(root / "browser-trace-macos-arm64.json"),
        },
        "buildTiming": {
            "path": "build-timing-macos-arm64.json",
            "sha256": sha256(root / "build-timing-macos-arm64.json"),
        },
        "harness": {"path": "harness.mjs", "sha256": "9" * 64},
    }
    _write_json(root / "delivery-report.json", delivery)
    reproducibility = {
        "status": "pending-external-provenance",
        "localComparisonStatus": "passed",
        "externalProvenanceStatus": "required",
        "requiredExternalBindings": [],
    }
    _write_json(root / "reproducibility-report.json", reproducibility)
    delivery_hash = sha256(root / "delivery-report.json")
    reproducibility_hash = sha256(root / "reproducibility-report.json")
    _write_json(
        root / "automated-gate.json",
        {
            "schemaVersion": 1,
            "gateId": "phase-0r-ar6-regional-release-v1",
            "issue": 110,
            "releaseId": binding["releaseId"],
            "scientificDisposition": "projection-only",
            "automatedValidation": "pending",
            "releaseDisposition": "pending-owner",
            "phase1Unlocked": False,
            "blockingChecks": ["crossEnvironmentReproducibility"],
            "fallback": "do-not-publish-or-unlock-phase-1",
            "checks": {
                **BUILD_CHECKS,
                "crossEnvironmentReproducibility": False,
                "deliveryMeasurements": True,
            },
            "evidenceBindings": {
                "candidateBindingSha256": binding_sha256(binding),
                "manifestSha256": binding["manifestSha256"],
                "deliveryReportSha256": delivery_hash,
                "deliveryTraceSha256": delivery["trace"]["sha256"],
                "buildTimingSha256": delivery["buildTiming"]["sha256"],
                "browserHarnessSha256": delivery["harness"]["sha256"],
                "reproducibilityReportSha256": reproducibility_hash,
            },
            "externalVerificationRequired": {
                "reproducibilityProvenance": {
                    "status": "pending-external-verification",
                    "provider": "github-actions",
                    "requiredExternalBindings": reproducibility[
                        "requiredExternalBindings"
                    ],
                }
            },
        },
    )
    hashes = {name: sha256(root / name) for name in owner_promotion._BUNDLE_FILES}
    (root / "checksums.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in hashes.items()),
        encoding="utf-8",
    )
    summary_files = {
        (owner_promotion.MAC_EVIDENCE_ROOT / name).as_posix(): digest
        for name, digest in {
            **hashes,
            "checksums.txt": sha256(root / "checksums.txt"),
        }.items()
    }
    _write_json(
        repository_root / owner_promotion.SUMMARY_PATH,
        {
            "schemaVersion": 1,
            "releaseId": binding["releaseId"],
            "sourceRevision": source_revision,
            "integrationPullRequest": 201,
            "committedEvidence": {"files": summary_files},
        },
    )
    return root


def _refresh_committed_bundle(repository_root: Path) -> None:
    root = repository_root / owner_promotion.MAC_EVIDENCE_ROOT
    hashes = {name: sha256(root / name) for name in owner_promotion._BUNDLE_FILES}
    (root / "checksums.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in hashes.items()),
        encoding="utf-8",
    )
    summary_path = repository_root / owner_promotion.SUMMARY_PATH
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["committedEvidence"]["files"] = {
        (owner_promotion.MAC_EVIDENCE_ROOT / name).as_posix(): digest
        for name, digest in {
            **hashes,
            "checksums.txt": sha256(root / "checksums.txt"),
        }.items()
    }
    _write_json(summary_path, summary)


def test_committed_bundle_is_bound_by_checksums_and_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _committed_bundle(tmp_path, _head())
    binding = json.loads((root / "candidate-binding.json").read_text())
    monkeypatch.setattr(owner_promotion, "_validate_binding", lambda value, **_: value)
    monkeypatch.setattr(
        owner_promotion,
        "_validate_delivery_report",
        lambda value, **_: value,
    )
    monkeypatch.setattr(
        owner_promotion,
        "_validate_reproducibility_report",
        lambda value, **_: value,
    )

    observed, _, _, hashes, integration_pr, _ = owner_promotion._load_committed_evidence(
        tmp_path,
        {
            "releaseContractId": "ar6-europe-regional-release-v1",
            "scientificDisposition": "projection-only",
        },
    )

    assert observed == binding
    assert integration_pr == 201
    assert set(hashes) == {*owner_promotion._BUNDLE_FILES, "checksums.txt"}


def test_committed_bundle_tampering_fails_before_owner_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _committed_bundle(tmp_path, _head())
    monkeypatch.setattr(owner_promotion, "_validate_binding", lambda value, **_: value)
    (root / "delivery-report.json").write_text('{"status":"failed"}\n')

    with pytest.raises(ScienceContractError, match="differs from checksums"):
        owner_promotion._load_committed_evidence(
            tmp_path,
            {
                "releaseContractId": "ar6-europe-regional-release-v1",
                "scientificDisposition": "projection-only",
            },
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemaVersion", True),
        ("issue", True),
        ("fallback", "publish-anyway"),
        ("unexpected", "claim"),
    ],
)
def test_committed_gate_requires_exact_contract_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    root = _committed_bundle(tmp_path, _head())
    gate_path = root / "automated-gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate[field] = value
    _write_json(gate_path, gate)
    _refresh_committed_bundle(tmp_path)
    monkeypatch.setattr(owner_promotion, "_validate_binding", lambda value, **_: value)
    monkeypatch.setattr(
        owner_promotion,
        "_validate_delivery_report",
        lambda value, **_: value,
    )
    monkeypatch.setattr(
        owner_promotion,
        "_validate_reproducibility_report",
        lambda value, **_: value,
    )

    with pytest.raises(ScienceContractError, match="strict pending-external"):
        owner_promotion._load_committed_evidence(
            tmp_path,
            {
                "releaseContractId": "ar6-europe-regional-release-v1",
                "scientificDisposition": "projection-only",
            },
        )


def test_committed_gate_rejects_nested_external_verification_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _committed_bundle(tmp_path, _head())
    gate_path = root / "automated-gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["externalVerificationRequired"]["unexpected"] = "claim"
    _write_json(gate_path, gate)
    _refresh_committed_bundle(tmp_path)
    monkeypatch.setattr(owner_promotion, "_validate_binding", lambda value, **_: value)
    monkeypatch.setattr(
        owner_promotion,
        "_validate_delivery_report",
        lambda value, **_: value,
    )
    monkeypatch.setattr(
        owner_promotion,
        "_validate_reproducibility_report",
        lambda value, **_: value,
    )

    with pytest.raises(ScienceContractError, match="external binding set"):
        owner_promotion._load_committed_evidence(
            tmp_path,
            {
                "releaseContractId": "ar6-europe-regional-release-v1",
                "scientificDisposition": "projection-only",
            },
        )


@pytest.mark.parametrize(
    ("field", "value", "nested"),
    [
        ("integrationPullRequest", True, False),
        ("unexpected", "claim", False),
        ("unexpected", "claim", True),
    ],
)
def test_committed_summary_requires_exact_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    nested: bool,
) -> None:
    _committed_bundle(tmp_path, _head())
    summary_path = tmp_path / owner_promotion.SUMMARY_PATH
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    target = summary["committedEvidence"] if nested else summary
    target[field] = value
    _write_json(summary_path, summary)
    monkeypatch.setattr(owner_promotion, "_validate_binding", lambda value, **_: value)
    monkeypatch.setattr(
        owner_promotion,
        "_validate_delivery_report",
        lambda value, **_: value,
    )
    monkeypatch.setattr(
        owner_promotion,
        "_validate_reproducibility_report",
        lambda value, **_: value,
    )

    with pytest.raises(ScienceContractError, match="summary is detached"):
        owner_promotion._load_committed_evidence(
            tmp_path,
            {
                "releaseContractId": "ar6-europe-regional-release-v1",
                "scientificDisposition": "projection-only",
            },
        )


def test_real_finalizer_output_hands_off_to_owner_validation(tmp_path: Path) -> None:
    inputs = _promotion_inputs(tmp_path)
    canonical_timing = tmp_path / "evidence/build-timing-macos-arm64.json"
    inputs["timing"].rename(canonical_timing)
    inputs["timing"] = canonical_timing
    canonical_trace = tmp_path / "evidence/browser-trace-macos-arm64.json"
    inputs["trace"].rename(canonical_trace)
    inputs["trace"] = canonical_trace
    gate = _finalize(inputs)
    delivery = create_delivery_report(
        inputs["candidate"],
        inputs["trace"],
        inputs["harness"],
        inputs["timing"],
        contract=inputs["release"],
    )
    binding = inputs["binding"]
    root = tmp_path / owner_promotion.MAC_EVIDENCE_ROOT
    root.mkdir(parents=True)
    _write_json(root / "candidate-binding.json", binding)
    shutil.copyfile(inputs["candidate"] / "build-receipt.json", root / "build-receipt.json")
    shutil.copyfile(inputs["timing"], root / "build-timing-macos-arm64.json")
    shutil.copyfile(inputs["trace"], root / "browser-trace-macos-arm64.json")
    (root / "delivery-report.json").write_text(
        json.dumps(delivery, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    shutil.copyfile(inputs["reproducibility"], root / "reproducibility-report.json")
    _write_json(root / "automated-gate.json", gate)
    hashes = {name: sha256(root / name) for name in owner_promotion._BUNDLE_FILES}
    (root / "checksums.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in hashes.items()),
        encoding="utf-8",
    )
    summary_hashes = {
        **hashes,
        "checksums.txt": sha256(root / "checksums.txt"),
    }
    _write_json(
        tmp_path / owner_promotion.SUMMARY_PATH,
        {
            "schemaVersion": 1,
            "releaseId": binding["releaseId"],
            "sourceRevision": binding["sourceRevision"],
            "integrationPullRequest": 201,
            "committedEvidence": {
                "files": {
                    (owner_promotion.MAC_EVIDENCE_ROOT / name).as_posix(): digest
                    for name, digest in summary_hashes.items()
                }
            },
        },
    )

    observed = owner_promotion._load_committed_evidence(
        tmp_path,
        inputs["release"],
    )

    assert observed[0] == binding
    assert observed[2] == gate
    assert observed[4] == 201
    assert observed[5] == delivery


def test_direct_descendant_accepts_only_complete_evidence_delta(tmp_path: Path) -> None:
    repository, source_revision, evidence_revision, _ = _evidence_repository(tmp_path)

    records = owner_promotion._verify_evidence_only_delta(
        repository,
        source_revision,
        evidence_revision,
    )

    assert set(records) == set(owner_promotion._REQUIRED_EVIDENCE_DELTA)
    assert all(record["status"] == "A" for record in records.values())
    assert all(len(record["sha256"]) == 64 for record in records.values())


@pytest.mark.parametrize(
    "extra_path",
    [
        "src/pipeline/searise_pipeline/release/gate.py",
        ".github/workflows/ci.yml",
        "src/pipeline/science/ar6-regional-release.json",
        "docs/architecture/README.md",
    ],
)
def test_evidence_delta_rejects_code_workflow_contract_and_unlisted_docs(
    tmp_path: Path,
    extra_path: str,
) -> None:
    repository, source_revision, evidence_revision, _ = _evidence_repository(
        tmp_path,
        extra_path=extra_path,
    )

    with pytest.raises(ScienceContractError, match="forbidden (path|change)"):
        owner_promotion._verify_evidence_only_delta(
            repository,
            source_revision,
            evidence_revision,
        )


def test_evidence_delta_rejects_deletion(tmp_path: Path) -> None:
    repository, source_revision, evidence_revision, _ = _evidence_repository(
        tmp_path,
        deleted_path="CHANGELOG.md",
    )

    with pytest.raises(ScienceContractError, match="forbidden change"):
        owner_promotion._verify_evidence_only_delta(
            repository,
            source_revision,
            evidence_revision,
        )


@pytest.mark.parametrize("entry_kind", ["symlink", "submodule"])
def test_evidence_delta_rejects_symlink_and_submodule(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    target = owner_promotion._REQUIRED_EVIDENCE_DELTA[0]
    options = {f"{entry_kind}_path": target}
    repository, source_revision, evidence_revision, _ = _evidence_repository(
        tmp_path,
        **options,
    )

    with pytest.raises(ScienceContractError, match="symlink or submodule"):
        owner_promotion._verify_evidence_only_delta(
            repository,
            source_revision,
            evidence_revision,
        )


def test_evidence_delta_rejects_uncommitted_checkout_tampering(tmp_path: Path) -> None:
    repository, source_revision, evidence_revision, _ = _evidence_repository(tmp_path)
    path = repository / owner_promotion._REQUIRED_EVIDENCE_DELTA[0]
    path.write_text("uncommitted replacement\n", encoding="utf-8")

    with pytest.raises(ScienceContractError, match="checkout bytes differ"):
        owner_promotion._verify_evidence_only_delta(
            repository,
            source_revision,
            evidence_revision,
        )


def test_evidence_delta_rejects_reverted_intermediate_code_change(tmp_path: Path) -> None:
    repository, source_revision, evidence_revision, _ = _evidence_repository(
        tmp_path,
        reverted_path="src/pipeline/searise_pipeline/release/gate.py",
    )

    with pytest.raises(ScienceContractError, match="forbidden (path|change)"):
        owner_promotion._verify_evidence_only_delta(
            repository,
            source_revision,
            evidence_revision,
        )


@pytest.mark.parametrize(
    ("decision", "unlocked"),
    [("approved", True), ("rejected", False)],
)
def test_protected_workflow_produces_bound_immutable_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    unlocked: bool,
) -> None:
    repository, source_revision, evidence_revision, merge_revision = _evidence_repository(
        tmp_path
    )
    mac, linux, report, gate, evidence_hashes, delivery = _promotion_evidence(
        source_revision
    )
    monkeypatch.setattr(
        owner_promotion,
        "_load_committed_evidence",
        lambda *_: (mac, report, gate, evidence_hashes, 201, delivery),
    )
    monkeypatch.setattr(
        owner_promotion,
        "create_delivery_report",
        lambda *_args, **_kwargs: delivery,
    )
    monkeypatch.setattr(
        owner_promotion,
        "candidate_binding",
        _candidate_oracle(mac, linux),
    )
    release_contract = json.loads(
        (REPOSITORY_ROOT / owner_promotion.CONTRACT_PATH).read_text(encoding="utf-8")
    )
    monkeypatch.setattr(owner_promotion, "load_json", lambda _: release_contract)
    output = tmp_path / "promotion"

    final_gate = owner_promotion.promote_phase_0r_release(
        "101",
        "202",
        decision,
        repository_root=repository,
        output_root=output,
        download_root=tmp_path / "download",
        context=_context(merge_revision),
        api=MockGitHubApi(
            source_revision,
            evidence_revision,
            master_revision=merge_revision,
            linux_binding=linux,
            mac_binding=mac,
        ),
    )

    assert final_gate["automatedValidation"] == "passed"
    assert final_gate["releaseDisposition"] == decision
    assert final_gate["phase1Unlocked"] is unlocked
    assert final_gate["checks"]["crossEnvironmentReproducibility"] is True
    integration = json.loads((output / "integration-merge.json").read_text())
    assert integration["candidateSourceSha"] == source_revision
    assert integration["evidenceHeadSha"] == evidence_revision
    assert set(integration["evidenceOnlyDelta"]) == set(owner_promotion._REQUIRED_EVIDENCE_DELTA)
    assert set(path.name for path in output.iterdir()) == {
        "owner-attestation.json",
        "integration-merge.json",
        "promotion.json",
        "final-gate.json",
        "checksums.txt",
    }
    assert "github-protected-environment" in (output / "owner-attestation.json").read_text()
    assert len((output / "checksums.txt").read_text().splitlines()) == 4


def test_owner_verification_uses_real_contract_aware_candidate_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, source_revision, evidence_revision, merge_revision = _evidence_repository(
        tmp_path
    )
    release = json.loads(
        (REPOSITORY_ROOT / owner_promotion.CONTRACT_PATH).read_text(encoding="utf-8")
    )
    candidate = tmp_path / "linux-candidate"
    _candidate(candidate)
    receipt_path = candidate / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["sourceRevision"] = source_revision
    receipt["environmentIdentity"] = _pinned_environment(
        release,
        platform="linux-x86_64-cp311",
        vector_platform="linux-x86_64",
        build_run_id="github-101-1-linux-x86_64",
    )
    _write_json(receipt_path, receipt)
    _seal(candidate)
    linux = owner_promotion.candidate_binding(candidate, contract=release)
    mac_candidate = tmp_path / "mac-candidate"
    shutil.copytree(candidate, mac_candidate)
    mac_receipt_path = mac_candidate / "build-receipt.json"
    mac_receipt = json.loads(mac_receipt_path.read_text(encoding="utf-8"))
    mac_receipt["environmentIdentity"] = _pinned_environment(
        release,
        platform="macos-arm64-cp39",
        vector_platform="darwin-arm64",
        build_run_id="github-101-1-macos-arm64",
    )
    _write_json(mac_receipt_path, mac_receipt)
    _seal(mac_candidate)
    mac = owner_promotion.candidate_binding(mac_candidate, contract=release)
    report = _reproducibility_report(release, mac, linux)
    gate = {
        "checks": {**BUILD_CHECKS, "crossEnvironmentReproducibility": False},
        "externalVerificationRequired": {
            "reproducibilityProvenance": {
                "status": "pending-external-verification",
                "provider": "github-actions",
                "requiredExternalBindings": report["requiredExternalBindings"],
            }
        },
    }
    trusted_input_hashes = {
        "build-timing-macos-arm64.json": hashlib.sha256(_timing_bytes(mac)).hexdigest(),
        "browser-trace-macos-arm64.json": hashlib.sha256(_trace_bytes()).hexdigest(),
    }
    monkeypatch.setattr(
        owner_promotion,
        "_load_committed_evidence",
        lambda *_: (
            mac,
            report,
            gate,
            trusted_input_hashes,
            201,
            _committed_delivery(mac),
        ),
    )
    monkeypatch.setattr(
        owner_promotion,
        "create_delivery_report",
        lambda *_args, **_kwargs: _committed_delivery(mac),
    )
    monkeypatch.setattr(owner_promotion, "load_json", lambda _: release)

    final_gate = owner_promotion.promote_phase_0r_release(
        "101",
        "202",
        "approved",
        repository_root=repository,
        output_root=tmp_path / "promotion-real-binding",
        download_root=tmp_path / "download-real-binding",
        context=_context(merge_revision),
        api=MockGitHubApi(
            source_revision,
            evidence_revision,
            master_revision=merge_revision,
            candidate=candidate,
            mac_candidate=mac_candidate,
            linux_binding=linux,
            mac_binding=mac,
        ),
    )

    assert final_gate["automatedValidation"] == "passed"
    assert final_gate["releaseDisposition"] == "approved"


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("GITHUB_REPOSITORY", "fork/SeaRise-Europe"),
        ("GITHUB_REF", "refs/heads/integration/phase-0r"),
        ("GITHUB_ACTOR", "another-user"),
        ("GITHUB_TRIGGERING_ACTOR", "another-user"),
        ("GITHUB_WORKFLOW_REF", "invented.yml@refs/heads/master"),
        ("SEARISE_OWNER_ENVIRONMENT", "unprotected"),
    ],
)
def test_authority_context_is_not_caller_selectable(
    field: str,
    invalid: str,
) -> None:
    source_revision = _head()
    context = _context(source_revision)
    context[field] = invalid

    with pytest.raises(ScienceContractError, match="authority boundary"):
        owner_promotion._validate_context(context, REPOSITORY_ROOT)


def test_owner_workflow_rerun_is_non_authoritative() -> None:
    context = _context(_head())
    context["GITHUB_RUN_ATTEMPT"] = "2"

    with pytest.raises(ScienceContractError, match="fresh workflow run"):
        owner_promotion._validate_context(context, REPOSITORY_ROOT)


@pytest.mark.parametrize("value", ["0", "01", "-1", "1.0", "true", ""])
def test_dispatch_identifiers_are_canonical_positive_decimals(value: str) -> None:
    with pytest.raises(ScienceContractError, match="positive decimal"):
        owner_promotion._exact_positive_decimal(value, "validation_run_id")


def test_cli_exposes_only_the_three_reviewed_dispatch_inputs() -> None:
    parser = _load_cli()._parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option not in {"-h", "--help"}
    }

    assert options == {"--validation-run-id", "--evidence-pr-number", "--decision"}


@pytest.mark.parametrize(
    ("response_path", "field", "invalid", "message"),
    [
        ("run", "conclusion", "failure", "provenance boundary"),
        ("run", "run_attempt", 2, "provenance boundary"),
        ("workflow", "path", "other.yml", "another workflow"),
        ("job", "conclusion", "failure", "jobs did not pass"),
        ("artifact", "name", "caller-selected.zip", "artifacts are unavailable"),
        ("integration_pull", "merge_commit_sha", "f" * 40, "Code integration"),
        ("evidence_pull", "merged", False, "Evidence-only pull request"),
        ("evidence_base", "sha", "f" * 40, "Evidence-only pull request"),
        ("source_compare", "status", "diverged", "not a direct descendant"),
    ],
)
def test_github_metadata_tampering_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response_path: str,
    field: str,
    invalid: object,
    message: str,
) -> None:
    source_revision = _head()
    evidence_revision = "e" * 40
    mac, linux, report, gate, evidence_hashes, delivery = _promotion_evidence(
        source_revision
    )
    monkeypatch.setattr(
        owner_promotion,
        "_load_committed_evidence",
        lambda *_: (mac, report, gate, evidence_hashes, 201, delivery),
    )
    monkeypatch.setattr(
        owner_promotion,
        "create_delivery_report",
        lambda *_args, **_kwargs: delivery,
    )
    monkeypatch.setattr(
        owner_promotion,
        "candidate_binding",
        _candidate_oracle(mac, linux),
    )
    monkeypatch.setattr(
        owner_promotion,
        "_verify_evidence_only_delta",
        lambda *_: {owner_promotion.SUMMARY_PATH.as_posix(): {}},
    )
    api = MockGitHubApi(
        source_revision,
        evidence_revision,
        master_revision=source_revision,
        linux_binding=linux,
        mac_binding=mac,
    )
    paths = {
        "run": f"/repos/{owner_promotion.REPOSITORY}/actions/runs/101",
        "workflow": f"/repos/{owner_promotion.REPOSITORY}/actions/workflows/303",
        "job": (
            f"/repos/{owner_promotion.REPOSITORY}/actions/runs/101/"
            "attempts/1/jobs?per_page=100"
        ),
        "artifact": f"/repos/{owner_promotion.REPOSITORY}/actions/runs/101/artifacts?per_page=100",
        "integration_pull": f"/repos/{owner_promotion.REPOSITORY}/pulls/201",
        "evidence_pull": f"/repos/{owner_promotion.REPOSITORY}/pulls/202",
        "evidence_base": f"/repos/{owner_promotion.REPOSITORY}/pulls/202",
        "source_compare": (
            f"/repos/{owner_promotion.REPOSITORY}/compare/{source_revision}...{evidence_revision}"
        ),
    }
    document = api.responses[paths[response_path]]
    if response_path in {"job", "artifact"}:
        collection = "jobs" if response_path == "job" else "artifacts"
        document[collection][0][field] = invalid
    elif response_path == "evidence_base":
        document["base"][field] = invalid
    else:
        document[field] = invalid

    with pytest.raises(ScienceContractError, match=message):
        owner_promotion.promote_phase_0r_release(
            "101",
            "202",
            "approved",
            repository_root=REPOSITORY_ROOT,
            output_root=tmp_path / "promotion",
            download_root=tmp_path / "download",
            context=_context(source_revision),
            api=api,
        )

    assert not (tmp_path / "promotion").exists()


def test_validation_run_requires_exactly_one_artifact(tmp_path: Path) -> None:
    source_revision = _head()
    api = MockGitHubApi(source_revision, "e" * 40, master_revision=source_revision)
    artifact_path = f"/repos/{owner_promotion.REPOSITORY}/actions/runs/101/artifacts?per_page=100"
    api.responses[artifact_path]["total_count"] = 3

    with pytest.raises(ScienceContractError, match="artifact inventory is incomplete"):
        owner_promotion._verify_validation_run(
            api,
            101,
            source_revision,
            tmp_path / "download",
        )


def test_downloaded_candidate_must_match_required_external_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_revision = _head()
    evidence_revision = "e" * 40
    mac, _, report, gate, evidence_hashes, delivery = _promotion_evidence(source_revision)
    release = json.loads(
        (REPOSITORY_ROOT / owner_promotion.CONTRACT_PATH).read_text(encoding="utf-8")
    )
    unexpected = _synthetic_binding(
        release,
        source_revision,
        _pinned_environment(
            release,
            platform="linux-x86_64-cp311",
            vector_platform="linux-x86_64",
            build_run_id="unexpected-build",
        ),
    )
    monkeypatch.setattr(
        owner_promotion,
        "_load_committed_evidence",
        lambda *_: (mac, report, gate, evidence_hashes, 201, delivery),
    )
    monkeypatch.setattr(
        owner_promotion,
        "create_delivery_report",
        lambda *_args, **_kwargs: delivery,
    )
    monkeypatch.setattr(
        owner_promotion,
        "candidate_binding",
        _candidate_oracle(mac, unexpected),
    )

    with pytest.raises(ScienceContractError, match="differ from committed"):
        owner_promotion.promote_phase_0r_release(
            "101",
            "202",
            "approved",
            repository_root=REPOSITORY_ROOT,
            output_root=tmp_path / "promotion",
            download_root=tmp_path / "download",
            context=_context(source_revision),
            api=MockGitHubApi(
                source_revision,
                evidence_revision,
                master_revision=source_revision,
                linux_binding=unexpected,
                mac_binding=mac,
            ),
        )


def test_validation_artifact_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "artifact.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape", "forbidden")

    with pytest.raises(ScienceContractError, match="unsafe path"):
        owner_promotion._safe_extract(
            archive,
            tmp_path / "extracted",
            platform="linux",
        )

    assert not (tmp_path / "escape").exists()


def test_artifact_download_drops_authorization_at_storage_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = owner_promotion.GitHubApi("secret-token")
    signed_url = (
        "https://productionresultssa.blob.core.windows.net/actions-results/a.zip?sig=x"
    )
    payload = b"validated artifact bytes"
    responses = iter(
        [
            FakeHttpResponse(302, "https://api.github.com", headers={"Location": signed_url}),
            FakeHttpResponse(
                200,
                signed_url,
                payload,
                headers={"Content-Length": str(len(payload))},
            ),
        ]
    )
    requests = []

    def open_without_redirect(request, *, timeout):
        requests.append((request, timeout))
        return next(responses)

    monkeypatch.setattr(api, "_open_no_redirect", open_without_redirect)
    destination = tmp_path / "artifact.zip"

    api.download("/repos/artemsemdev/SeaRise-Europe/actions/artifacts/1/zip", destination)

    first_headers = dict(requests[0][0].header_items())
    second_headers = dict(requests[1][0].header_items())
    assert first_headers["Authorization"] == "Bearer secret-token"
    assert "Authorization" not in second_headers
    assert requests[1][0].full_url == signed_url
    assert destination.read_bytes() == payload


@pytest.mark.parametrize(
    "location",
    [
        "http://productionresultssa.blob.core.windows.net/a.zip?sig=x",
        "https://evil.example/a.zip?sig=x",
        "https://user@productionresultssa.blob.core.windows.net/a.zip?sig=x",
    ],
)
def test_artifact_download_rejects_untrusted_redirect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    api = owner_promotion.GitHubApi("secret-token")
    monkeypatch.setattr(
        api,
        "_open_no_redirect",
        lambda *_args, **_kwargs: FakeHttpResponse(
            302,
            "https://api.github.com",
            headers={"Location": location},
        ),
    )

    with pytest.raises(ScienceContractError, match="trusted HTTPS storage"):
        api.download(
            "/repos/artemsemdev/SeaRise-Europe/actions/artifacts/1/zip",
            tmp_path / "artifact.zip",
        )


def test_artifact_download_rejects_second_redirect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = owner_promotion.GitHubApi("secret-token")
    signed_url = (
        "https://productionresultssa.blob.core.windows.net/actions-results/a.zip?sig=x"
    )
    responses = iter(
        [
            FakeHttpResponse(302, "https://api.github.com", headers={"Location": signed_url}),
            FakeHttpResponse(302, signed_url, headers={"Location": signed_url}),
        ]
    )
    monkeypatch.setattr(
        api,
        "_open_no_redirect",
        lambda *_args, **_kwargs: next(responses),
    )

    with pytest.raises(ScienceContractError, match="unexpected redirect"):
        api.download(
            "/repos/artemsemdev/SeaRise-Europe/actions/artifacts/1/zip",
            tmp_path / "artifact.zip",
        )


@pytest.mark.parametrize(
    ("platform", "timing_name"),
    [
        ("linux", "build-timing-macos-arm64.json"),
        ("macos", "build-timing-linux.json"),
        ("linux", None),
    ],
)
def test_validation_artifact_rejects_swapped_or_missing_platform_timing(
    tmp_path: Path,
    platform: str,
    timing_name: str | None,
) -> None:
    archive = tmp_path / f"{platform}.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            f"{owner_promotion.LINUX_CANDIDATE_DIRECTORY}/placeholder",
            "candidate",
        )
        if timing_name is not None:
            bundle.writestr(timing_name, "{}\n")

    with pytest.raises(ScienceContractError, match="unexpected path|lacks required"):
        owner_promotion._safe_extract(
            archive,
            tmp_path / f"extract-{platform}",
            platform=platform,
        )


@pytest.mark.parametrize("mutation", ["digest", "size", "workflow", "job-id"])
def test_validation_artifact_metadata_is_bound_to_exact_run(
    tmp_path: Path,
    mutation: str,
) -> None:
    source_revision = _head()
    api = MockGitHubApi(source_revision, "e" * 40, master_revision=source_revision)
    artifacts_path = (
        f"/repos/{owner_promotion.REPOSITORY}/actions/runs/101/artifacts?per_page=100"
    )
    jobs_path = (
        f"/repos/{owner_promotion.REPOSITORY}/actions/runs/101/"
        "attempts/1/jobs?per_page=100"
    )
    if mutation == "digest":
        api.responses[artifacts_path]["artifacts"][0]["digest"] = f"sha256:{'0' * 64}"
    elif mutation == "size":
        api.responses[artifacts_path]["artifacts"][0]["size_in_bytes"] += 1
    elif mutation == "workflow":
        api.responses[artifacts_path]["artifacts"][0]["workflow_run"]["head_sha"] = (
            "f" * 40
        )
    else:
        api.responses[jobs_path]["jobs"][1]["id"] = api.responses[jobs_path]["jobs"][0][
            "id"
        ]

    with pytest.raises(ScienceContractError):
        owner_promotion._verify_validation_run(
            api,
            101,
            source_revision,
            tmp_path / "download",
        )


@pytest.mark.parametrize("state", ["queued", "in_progress"])
def test_concurrent_owner_decision_is_rejected(state: str) -> None:
    source_revision = _head()
    api = MockGitHubApi(source_revision, "e" * 40, master_revision=source_revision)
    history_path = (
        f"/repos/{owner_promotion.REPOSITORY}/actions/workflows/"
        "phase-0r-owner-promotion.yml/runs?event=workflow_dispatch&per_page=100"
    )
    api.responses[history_path] = {
        "total_count": 1,
        "workflow_runs": [{"id": 8000, "status": state}],
    }

    with pytest.raises(ScienceContractError, match="concurrent owner decision"):
        owner_promotion._verify_no_prior_decision(
            api,
            101,
            202,
            "phase-0r-ar6-v1",
            source_revision,
            _context(source_revision),
            REPOSITORY_ROOT,
        )


def test_prior_successful_decision_for_candidate_is_immutable() -> None:
    source_revision = _head()
    api = MockGitHubApi(source_revision, "e" * 40, master_revision=source_revision)
    history_path = (
        f"/repos/{owner_promotion.REPOSITORY}/actions/workflows/"
        "phase-0r-owner-promotion.yml/runs?event=workflow_dispatch&per_page=100"
    )
    prior_run_id = 8000
    api.responses[history_path] = {
        "total_count": 1,
        "workflow_runs": [
            {
                "id": prior_run_id,
                "display_title": owner_promotion._decision_title(101, 199),
                "status": "completed",
                "conclusion": "success",
                "event": "workflow_dispatch",
                "run_attempt": 1,
                "path": owner_promotion.OWNER_WORKFLOW,
                "head_branch": "master",
                "repository": {"full_name": owner_promotion.REPOSITORY},
                "actor": {"login": owner_promotion.OWNER_LOGIN},
                "triggering_actor": {"login": owner_promotion.OWNER_LOGIN},
            }
        ],
    }
    api.responses[
        f"/repos/{owner_promotion.REPOSITORY}/actions/runs/{prior_run_id}/artifacts?per_page=100"
    ] = {
        "total_count": 1,
        "artifacts": [
            {
                "id": 7000,
                "name": owner_promotion._decision_artifact_name(
                    "phase-0r-ar6-v1", source_revision
                ),
                "expired": False,
            }
        ],
    }

    with pytest.raises(ScienceContractError, match="already exists"):
        owner_promotion._verify_no_prior_decision(
            api,
            101,
            202,
            "phase-0r-ar6-v1",
            source_revision,
            _context(source_revision),
            REPOSITORY_ROOT,
        )


def test_permanent_owner_record_blocks_another_decision(tmp_path: Path) -> None:
    repository, _, _, _ = _evidence_repository(tmp_path)
    record_root = repository / owner_promotion.OWNER_RECORD_ROOT
    record_root.mkdir(parents=True)
    for name in owner_promotion._OWNER_RECORD_FILES:
        (record_root / name).write_text(f"permanent {name}\n", encoding="utf-8")
    _git(repository, "add", owner_promotion.OWNER_RECORD_ROOT.as_posix())
    _git(repository, "commit", "-m", "docs: persist owner decision")
    source_revision = _git(repository, "rev-parse", "HEAD")
    api = MockGitHubApi(source_revision, source_revision, master_revision=source_revision)

    with pytest.raises(ScienceContractError, match="permanent authoritative"):
        owner_promotion._verify_no_prior_decision(
            api,
            101,
            202,
            "phase-0r-ar6-v1",
            source_revision,
            _context(source_revision),
            repository,
        )
