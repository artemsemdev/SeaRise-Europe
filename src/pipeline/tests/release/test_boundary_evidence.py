"""Candidate-bound evidence orchestration for real boundary PMTiles builds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import searise_pipeline.release.boundary_evidence as boundary_evidence
from searise_pipeline.release import (
    BoundaryGeoParquetEvidence,
    BoundaryPmtilesEvidence,
    BoundaryVectorToolPaths,
    VectorToolchainEvidence,
)
from searise_pipeline.release.toolchain import PythonToolchainEvidence
from searise_pipeline.science import ScienceContractError


def _vector_evidence() -> VectorToolchainEvidence:
    return VectorToolchainEvidence(
        tippecanoe_version="2.79.0",
        tippecanoe_source_sha256="a" * 64,
        tippecanoe_binary_sha256="b" * 64,
        pmtiles_version="1.31.2",
        pmtiles_commit="a3e4951ea6a0477b784c27c1dcbfd9c130878c5a",
        pmtiles_binary_sha256="c" * 64,
        pmtiles_distribution_platform="darwin-arm64",
        pmtiles_distribution_sha256="d" * 64,
        decode_binary_sha256="e" * 64,
    )


def _python_evidence() -> PythonToolchainEvidence:
    return PythonToolchainEvidence(
        platform="macos-arm64-cp311",
        python_version="3.11.9",
        lock_path="src/pipeline/requirements-release-macos-arm64.lock",
        lock_sha256="f" * 64,
        packages={"shapely": "2.0.7"},
        gdal_version="3.9.3",
        rasterio_proj_version="9.4.1",
        pyproj_proj_version="9.3.0",
    )


def _arrange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    nondeterministic: bool = False,
) -> tuple[Path, Path, BoundaryVectorToolPaths]:
    repository = tmp_path / "repository"
    for relative in (
        "data/geometry/europe.geojson",
        "data/geometry/coastal_analysis_zone.geojson",
    ):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    contract = repository / "src/pipeline/science/ar6-regional-release.json"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text('{"toolchain":{}}\n', encoding="utf-8")
    lock = repository / "src/pipeline/requirements-release-macos-arm64.lock"
    lock.write_text("fixture\n", encoding="utf-8")
    receipt = repository / "src/pipeline/toolchain/tippecanoe-receipt.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text('{"schemaVersion":1}\n', encoding="utf-8")
    browser_harness = repository / "src/frontend/scripts/browser.mjs"
    browser_harness.parent.mkdir(parents=True, exist_ok=True)
    browser_harness.write_text("// fixture\n", encoding="utf-8")
    tool = tmp_path / "tool"
    tool.write_bytes(b"tool")
    tools = BoundaryVectorToolPaths(
        tippecanoe=tool,
        decode=tool,
        pmtiles=tool,
        tippecanoe_source=tool,
        tippecanoe_build_receipt=receipt,
        pmtiles_distribution_asset=tool,
        platform="darwin-arm64",
    )
    monkeypatch.setattr(
        boundary_evidence,
        "validate_python_toolchain",
        lambda *_args, **_kwargs: _python_evidence(),
    )
    monkeypatch.setattr(
        BoundaryVectorToolPaths,
        "validate",
        lambda *_args, **_kwargs: _vector_evidence(),
    )

    def write_geoparquet(
        source: Path, output: Path, *, role: str
    ) -> BoundaryGeoParquetEvidence:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"parquet:{role}".encode())
        return BoundaryGeoParquetEvidence(
            path=boundary_evidence._ROLES[role]["geoparquet"],
            role=role,
            byte_size=output.stat().st_size,
            sha256=boundary_evidence.sha256(output),
            source_sha256=boundary_evidence.sha256(source),
            row_count=1,
        )

    calls = 0

    def write_pmtiles(
        source: Path,
        _geojson: Path,
        output: Path,
        *,
        role: str,
        **_kwargs: object,
    ) -> BoundaryPmtilesEvidence:
        nonlocal calls
        calls += 1
        suffix = f":{calls}" if nondeterministic else ""
        output.write_bytes(f"pmtiles:{role}{suffix}".encode())
        return BoundaryPmtilesEvidence(
            path=boundary_evidence._ROLES[role]["pmtiles"],
            byte_size=output.stat().st_size,
            sha256=boundary_evidence.sha256(output),
            source_geoparquet_byte_size=source.stat().st_size,
            source_geoparquet_sha256=boundary_evidence.sha256(source),
            decoded_fragment_count=7,
            geometry_parity={
                "comparison": (
                    "symmetric-vertex-to-boundary-discrete-distance-"
                    "plus-per-axis-envelope"
                ),
                "distance": {"symmetricMaximumDegrees": 0.00001},
            },
            visual_intermediary={
                "canonicalSourceModified": False,
                "maximumSegmentLengthDegrees": 0.10,
            },
            header={"spec_version": 3, "minzoom": 0, "maxzoom": 6},
            metadata={"searise": {"status": "selected-scope-approximation"}},
            toolchain=_vector_evidence(),
        )

    monkeypatch.setattr(boundary_evidence, "write_boundary_geoparquet", write_geoparquet)
    monkeypatch.setattr(boundary_evidence, "write_boundary_pmtiles", write_pmtiles)
    monkeypatch.setattr(
        boundary_evidence,
        "evaluate_boundary_profile_matrix",
        lambda *_args, **_kwargs: [
            {
                "fullDetail": detail,
                "passed": detail == 17,
                "profileId": f"detail-{detail}-{segmentization}",
                "visualIntermediary": {"method": segmentization},
            }
            for detail in (14, 17)
            for segmentization in ("none", "shapely-segmentize")
        ],
    )

    def browser_report(output: Path, **_kwargs: object) -> dict[str, object]:
        output.write_text('{"status":"passed"}\n', encoding="utf-8")
        return {
            "path": output.name,
            "byteSize": output.stat().st_size,
            "sha256": boundary_evidence.sha256(output),
        }

    monkeypatch.setattr(boundary_evidence, "_run_browser_harness", browser_report)
    return repository, lock, tools


def test_build_boundary_evidence_publishes_complete_candidate_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, lock, tools = _arrange(tmp_path, monkeypatch)
    output = tmp_path / "evidence"
    result = boundary_evidence.build_boundary_evidence_package(
        output,
        repository=repository,
        source_revision="1" * 40,
        build_run_id="github-123-1-darwin-arm64",
        release_contract_path=(
            repository / "src/pipeline/science/ar6-regional-release.json"
        ),
        python_lock_path=lock,
        tools=tools,
        node_path=tools.tippecanoe,
        browser_harness_path=repository / "src/frontend/scripts/browser.mjs",
        frontend_directory=repository / "src/frontend",
    )

    assert result == output
    report = json.loads((output / "validation-report.json").read_text())
    receipt = json.loads((output / "build-receipt.json").read_text())
    assert report["status"] == "passed"
    assert report["candidate"]["sourceRevision"] == "1" * 40
    assert [item["role"] for item in report["artifacts"]] == [
        "coastal-boundary",
        "support-boundary",
    ]
    assert receipt["reproducibility"] == {
        "independentBuildAttempts": 2,
        "artifactInventoryIdentical": True,
        "artifactBytesIdentical": True,
        "inspectionEvidenceIdentical": True,
    }
    assert len(receipt["outputs"]) == 4
    assert receipt["profileSelection"]["path"] == "profile-selection.json"
    profile_selection = json.loads((output / "profile-selection.json").read_text())
    assert profile_selection["selection"] == {
        "fullDetail": 17,
        "mvtExtent": 131072,
        "visualSegmentizationDegrees": 0.10,
        "canonicalSourceModified": False,
    }
    assert len(profile_selection["roles"]) == 2
    assert receipt["browserHarness"]["report"]["path"] == (
        "browser-consumer-report.json"
    )
    assert len((output / "checksums.txt").read_text().splitlines()) == 8
    with pytest.raises(ScienceContractError, match="already exists"):
        boundary_evidence.build_boundary_evidence_package(
            output,
            repository=repository,
            source_revision="1" * 40,
            build_run_id="github-123-1-darwin-arm64",
            release_contract_path=(
                repository / "src/pipeline/science/ar6-regional-release.json"
            ),
            python_lock_path=lock,
            tools=tools,
            node_path=tools.tippecanoe,
            browser_harness_path=repository / "src/frontend/scripts/browser.mjs",
            frontend_directory=repository / "src/frontend",
        )


def test_build_boundary_evidence_rejects_non_deterministic_bytes_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, lock, tools = _arrange(
        tmp_path, monkeypatch, nondeterministic=True
    )
    output = tmp_path / "evidence"
    with pytest.raises(ScienceContractError, match="rebuild bytes differ"):
        boundary_evidence.build_boundary_evidence_package(
            output,
            repository=repository,
            source_revision="2" * 40,
            build_run_id="github-124-1-darwin-arm64",
            release_contract_path=(
                repository / "src/pipeline/science/ar6-regional-release.json"
            ),
            python_lock_path=lock,
            tools=tools,
            node_path=tools.tippecanoe,
            browser_harness_path=repository / "src/frontend/scripts/browser.mjs",
            frontend_directory=repository / "src/frontend",
        )
    assert not output.exists()


@pytest.mark.parametrize("unsafe", [False, True])
def test_browser_harness_binds_candidate_and_safe_limitations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe: bool,
) -> None:
    candidate = tmp_path / "candidate"
    artifacts = {
        "boundaries/coastal-analysis-zone.pmtiles": b"coastal",
        "boundaries/europe.pmtiles": b"support",
    }
    for relative, payload in artifacts.items():
        path = candidate / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    node = tmp_path / "node"
    harness = tmp_path / "browser.mjs"
    frontend = tmp_path / "frontend"
    node.write_bytes(b"node")
    harness.write_text("// fixture\n", encoding="utf-8")
    frontend.mkdir()
    output = tmp_path / "browser-report.json"

    def run(command: list[str], **_kwargs: object) -> None:
        report_path = Path(command[-1])
        report_path.write_text(
            json.dumps(
                {
                    "status": "passed",
                    "inputs": [
                        {
                            "path": relative,
                            "byteSize": len(payload),
                            "sha256": boundary_evidence.sha256(candidate / relative),
                        }
                        for relative, payload in artifacts.items()
                    ],
                    "assertions": {
                        "zooms": [0, 3, 6],
                        "roles": ["coastal-boundary", "support-boundary"],
                        "everySampleDecodedAndRendered": True,
                        "safeVisualPropertiesPreserved": True,
                        "httpRangeUsedForEveryArtifact": True,
                    },
                    "samples": [{} for _ in range(6)],
                    "limitation": {
                        "visualOnly": True,
                        "engineeringUse": "engineering-only",
                        "canonical": unsafe,
                        "production": False,
                        "publicationEligible": False,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(boundary_evidence.subprocess, "run", run)
    if unsafe:
        with pytest.raises(ScienceContractError, match="browser report differs"):
            boundary_evidence._run_browser_harness(
                output,
                candidate=candidate,
                node_path=node,
                browser_harness_path=harness,
                frontend_directory=frontend,
            )
    else:
        record = boundary_evidence._run_browser_harness(
            output,
            candidate=candidate,
            node_path=node,
            browser_harness_path=harness,
            frontend_directory=frontend,
        )
        assert record["path"] == "browser-report.json"
        assert record["sha256"] == boundary_evidence.sha256(output)
