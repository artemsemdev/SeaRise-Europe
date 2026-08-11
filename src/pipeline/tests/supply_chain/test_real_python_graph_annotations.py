"""Checks for reviewed release and settlement-spatial Python graphs."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    validate_python_lock_graph,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
GRAPH_ROOT = REPOSITORY_ROOT / "contracts" / "supply-chain" / "v1" / "python-graphs"
RELEASE = GRAPH_ROOT / "release-runtime.json"
SPATIAL = GRAPH_ROOT / "settlement-spatial-runtime.json"
EXPECTED_ROOTS = {
    "click",
    "cryptography",
    "geopandas",
    "importlib-metadata",
    "jsonschema",
    "netcdf4",
    "numpy",
    "pandas",
    "pyarrow",
    "pyproj",
    "rasterio",
    "rio-cogeo",
    "shapely",
    "xarray",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def _write(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("path", "locks", "package_count", "roots", "edge_count"),
    [
        (
            RELEASE,
            [
                "src/pipeline/requirements-release.lock",
                "src/pipeline/requirements-release-macos-arm64.lock",
            ],
            39,
            EXPECTED_ROOTS,
            58,
        ),
        (
            SPATIAL,
            [
                "src/pipeline/requirements-settlements-spatial-linux-x86_64.lock",
                "src/pipeline/requirements-settlements-spatial-macos-arm64.lock",
            ],
            1,
            {"duckdb"},
            0,
        ),
    ],
)
def test_real_graphs_bind_exact_paired_locks_and_reviewed_counts(
    path: Path,
    locks: list[str],
    package_count: int,
    roots: set[str],
    edge_count: int,
) -> None:
    document = validate_python_lock_graph(path, repository_root=REPOSITORY_ROOT)

    assert document["review"]["status"] == "reviewed-wheel-metadata"
    assert document["review"]["productionClaim"] is False
    assert [target["id"] for target in document["targets"]] == [
        "linux-x86-64-cp311",
        "macos-arm64-cp311",
    ]
    assert [target["lock"]["path"] for target in document["targets"]] == locks
    for target in document["targets"]:
        lock = REPOSITORY_ROOT / target["lock"]["path"]
        assert target["lock"]["sha256"] == hashlib.sha256(lock.read_bytes()).hexdigest()

    packages = document["packages"]
    assert len(packages) == package_count
    assert {item["name"] for item in packages if item["root"]} == roots
    assert sum(len(item["dependencies"]) for item in packages) == edge_count
    assert all(item["selectedExtras"] == [] for item in packages)


@pytest.mark.parametrize("source", [RELEASE, SPATIAL])
def test_real_graphs_reject_target_identity_drift(tmp_path: Path, source: Path) -> None:
    document = _load(source)
    document["targets"][0]["markerEnvironment"]["platform_machine"] = "arm64"
    annotation = tmp_path / source.name
    _write(annotation, document)

    with pytest.raises(SupplyChainContractError, match="platform identity"):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)


@pytest.mark.parametrize("source", [RELEASE, SPATIAL])
def test_real_graphs_reject_lock_and_graph_mutation(tmp_path: Path, source: Path) -> None:
    document = _load(source)
    annotation = tmp_path / source.name
    mutated = copy.deepcopy(document)
    mutated["packages"][0]["version"] = "0.0.0"
    _write(annotation, mutated)
    with pytest.raises(SupplyChainContractError, match="package parity"):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)

    document["targets"][0]["lock"]["sha256"] = "0" * 64
    _write(annotation, document)
    with pytest.raises(SupplyChainContractError, match="lock SHA-256 mismatch"):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)
