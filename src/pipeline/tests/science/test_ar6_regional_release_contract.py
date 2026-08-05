"""Protect the production AR6 regional release contract."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from searise_pipeline.release import load_release_contract
from searise_pipeline.science import ScienceContractError

CONTRACT_DIR = Path(__file__).parents[2] / "science"


def _load(name: str) -> dict[str, object]:
    return json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))


def test_release_contract_matches_schema_and_source_identity() -> None:
    contract = _load("ar6-regional-release.json")
    schema = _load("ar6-regional-release.schema.json")

    Draft202012Validator(schema).validate(contract)
    assert contract["source"] == {
        "sourceId": "ipcc-ar6-sea-level",
        "version": "20210809",
        "archiveSha256": "d3b1c2ed093cca491db2461e67b782bcca98763d326378ffee39908c2b094e91",
        "canonicalRecord": "https://zenodo.org/records/6382554",
        "licence": "CC-BY-4.0",
        "licenceUrl": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": (
            "Garner et al. (2021), IPCC AR6 Sea Level Projections, version 20210809, "
            "doi:10.5281/zenodo.5914709."
        ),
        "requiredAcknowledgements": [
            "Cite IPCC AR6 Working Group I Chapter 9, the FACTS model description, and "
            "dataset version 20210809.",
            "Thank the projection authors, supporting funding agencies, and NASA Sea Level "
            "Change Team as required by the canonical record.",
        ],
    }


def test_release_contract_keeps_exact_lookup_separate_from_visuals() -> None:
    artifacts = _load("ar6-regional-release.json")["artifacts"]

    assert artifacts["cog"]["role"] == "exact-browser-lookup"
    assert artifacts["geoparquet"] == {
        "role": "analytical-parity",
        "count": 1,
        "schemaVersion": "1.1.0",
        "geometryEncoding": "WKB",
        "geometryType": "Point",
        "crs": "OGC:CRS84",
        "compression": "zstd",
        "rowGroupSize": 1024,
        "rows": "valid-source-locations-only",
        "nearestSelection": "prohibited",
    }
    assert artifacts["pmtiles"]["role"] == "visual-only"
    assert artifacts["pmtiles"]["scientificLookup"] == "prohibited"


def test_release_contract_pins_native_grid_and_zero_scientific_tolerance() -> None:
    contract = _load("ar6-regional-release.json")

    assert contract["grid"] == {
        "crs": "EPSG:4326",
        "nativeResolutionDegrees": 1,
        "longitudeCentres": [-30, 45],
        "latitudeCentres": [30, 75],
        "width": 76,
        "height": 46,
        "bounds": [-30.5, 29.5, 45.5, 75.5],
        "scientificResampling": "none",
    }
    assert contract["reproducibility"]["scientificValueToleranceMillimetres"] == 0
    assert contract["reproducibility"]["validIdSetDifference"] == 0
    assert contract["budgets"] == {
        "cogTotalBytes": 262144,
        "pmtilesTotalBytes": 6291456,
        "geoparquetBytes": 1048576,
        "coreArtifactsTotalBytes": 8388608,
        "buildDurationSeconds": 60,
        "browserHeapBytes": 67108864,
        "rangeRequestCount": 4,
        "coldTransferBytes": 262144,
        "lookupP95Milliseconds": 50,
    }


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("budgets", "rangeRequestCount", 5),
        ("artifacts", "cog", {}),
        ("toolchain", "tippecanoe", {}),
    ],
)
def test_release_contract_loader_rejects_semantic_mutations(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    release = _load("ar6-regional-release.json")
    release[section][key] = value
    contract_path = tmp_path / "ar6-regional-release.json"
    schema_path = tmp_path / "ar6-regional-release.schema.json"
    contract_path.write_text(json.dumps(release), encoding="utf-8")
    shutil.copyfile(CONTRACT_DIR / schema_path.name, schema_path)

    with pytest.raises(ScienceContractError, match="Invalid AR6 regional"):
        load_release_contract(contract_path)
