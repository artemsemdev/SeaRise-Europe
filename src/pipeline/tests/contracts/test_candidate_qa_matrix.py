from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from searise_pipeline.candidate_completeness.qa_matrix import (
    MATRIX_PATH,
    CandidateContractError,
    load_qa_routing_matrix,
)


def _load() -> dict[str, Any]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_matrix_covers_the_version_selected_inventory_without_count_constants() -> None:
    matrix = load_qa_routing_matrix()
    inventory = json.loads(matrix.candidate_inventory.read_text(encoding="utf-8"))
    expected = {
        (item["role"], item["mediaType"], item["contentEncoding"])
        for item in inventory["requiredArtifacts"]
    }
    observed = {
        (route.selector.role, route.selector.media_type, route.selector.content_encoding)
        for route in matrix.routes
    }
    assert observed == expected
    assert all("pending" not in route.validator_id for route in matrix.routes)


@pytest.mark.parametrize("mutation", ["missing", "unknown", "duplicate", "unsorted"])
def test_matrix_drift_fails_closed(tmp_path: Path, mutation: str) -> None:
    document = _load()
    if mutation == "missing":
        document["routes"].pop()
    elif mutation == "unknown":
        document["routes"][-1]["role"] = "unknown-role"
    elif mutation == "duplicate":
        document["routes"].append(document["routes"][-1])
    else:
        document["routes"][0], document["routes"][1] = (
            document["routes"][1],
            document["routes"][0],
        )
    with pytest.raises(CandidateContractError) as caught:
        load_qa_routing_matrix(_write(tmp_path, document))
    assert caught.value.code in {"qa-matrix", "qa-matrix-coverage"}
