"""Test deterministic source fixtures against independent AR6 goldens."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import runpy
from pathlib import Path

import numpy as np
import pytest

from searise_pipeline.release import (
    load_release_contract,
    load_source_fixture,
    rebind_source_fixture_contract,
    write_source_fixture,
)
from searise_pipeline.release.model import assert_source_integrity
from searise_pipeline.science import ScienceContractError

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_PATH = REPO_ROOT / "src/pipeline/science/ar6-regional-release.json"
FIXTURE_DIR = REPO_ROOT / "src/pipeline/fixtures/ar6-regional-release"
GOLDENS_PATH = REPO_ROOT / "src/pipeline/science/evidence/ar6-lookup-goldens.json"
REBIND_SCRIPT = REPO_ROOT / "scripts/science/rebind_ar6_release_fixture.py"


def contract() -> dict[str, object]:
    return dict(load_release_contract(CONTRACT_PATH))


def fixture_source():
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    return load_source_fixture(
        FIXTURE_DIR / "source-fixture.json.gz",
        receipt=receipt,
        release_contract=contract(),
    )


def test_offline_source_fixture_is_byte_deterministic_and_verified(tmp_path: Path) -> None:
    source = fixture_source()
    first = tmp_path / "first.json.gz"
    second = tmp_path / "second.json.gz"

    receipt = write_source_fixture(source, first)
    second_receipt = write_source_fixture(source, second)
    restored = load_source_fixture(first, receipt=receipt, release_contract=contract())

    assert first.read_bytes() == second.read_bytes()
    assert receipt == second_receipt
    assert restored.source_mode == "offline-real-source-fixture"
    assert restored.archive_sha256 == source.archive_sha256
    assert np.array_equal(restored.location_ids, source.location_ids)
    for expected, actual in zip(source.layers, restored.layers):
        assert (actual.scenario, actual.horizon, actual.member_sha256) == (
            expected.scenario,
            expected.horizon,
            expected.member_sha256,
        )
        assert np.array_equal(actual.lower_mm, expected.lower_mm)
        assert np.array_equal(actual.central_mm, expected.central_mm)
        assert np.array_equal(actual.upper_mm, expected.upper_mm)


def test_offline_source_fixture_fails_closed_on_tamper(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json.gz"
    receipt = write_source_fixture(fixture_source(), path)
    path.write_bytes(path.read_bytes()[:-1] + b"x")

    with pytest.raises(ScienceContractError, match="integrity mismatch"):
        load_source_fixture(path, receipt=receipt, release_contract=contract())


def test_checked_in_fixture_matches_independent_ar6_goldens() -> None:
    source = fixture_source()
    goldens = json.loads(GOLDENS_PATH.read_text(encoding="utf-8"))
    layers = {(layer.scenario, layer.horizon): layer for layer in source.layers}

    assert [int(layer.valid.sum()) for layer in source.layers] == [
        3055,
        3055,
        3055,
        3054,
        3054,
        3054,
        3054,
        3054,
        3054,
    ]
    for result in goldens["results"]:
        if result["state"] != "ProjectionAvailable":
            continue
        positions = np.argwhere(source.location_ids == result["source"]["locationId"])
        assert positions.shape == (1, 2)
        row, column = positions[0]
        for projection in result["projections"]:
            layer = layers[(projection["scenario"], projection["horizon"])]
            assert (
                int(layer.lower_mm[row, column]),
                int(layer.central_mm[row, column]),
                int(layer.upper_mm[row, column]),
            ) == (
                projection["lowerMillimetres"],
                projection["centralMillimetres"],
                projection["upperMillimetres"],
            )


def test_source_content_seal_rejects_post_verification_array_mutation() -> None:
    source = fixture_source()
    layer = source.layers[0]
    layer.central_mm.flags.writeable = True
    layer.central_mm[0, 0] = layer.central_mm[0, 0] + 1

    with pytest.raises(ScienceContractError, match="changed after verification"):
        assert_source_integrity(source, contract(), require_verified_archive=False)


def test_fixture_writer_rejects_mutated_source_before_creating_output(
    tmp_path: Path,
) -> None:
    source = fixture_source()
    layer = source.layers[0]
    layer.central_mm.flags.writeable = True
    layer.central_mm[0, 0] = layer.central_mm[0, 0] + 1
    output = tmp_path / "mutated.json.gz"

    with pytest.raises(ScienceContractError, match="changed after verification"):
        write_source_fixture(source, output)

    assert not output.exists()


def test_contract_rebind_preserves_science_and_removes_archive_capability(
    tmp_path: Path,
) -> None:
    current_path = FIXTURE_DIR / "source-fixture.json.gz"
    current_receipt = json.loads(
        (FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8")
    )
    original_document = json.loads(gzip.decompress(current_path.read_bytes()))
    previous_contract_sha256 = "1" * 64
    original_document["releaseContractSha256"] = previous_contract_sha256
    previous_payload = (
        json.dumps(original_document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    previous_buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=previous_buffer, mtime=0) as stream:
        stream.write(previous_payload)
    previous_path = tmp_path / "previous-source-fixture.json.gz"
    previous_path.write_bytes(previous_buffer.getvalue())
    previous_receipt = dict(current_receipt)
    previous_receipt.update(
        {
            "byteSize": previous_path.stat().st_size,
            "sha256": hashlib.sha256(previous_path.read_bytes()).hexdigest(),
            "releaseContractSha256": previous_contract_sha256,
        }
    )
    previous_receipt_bytes = (json.dumps(previous_receipt, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    rebound_bytes, rebound_receipt = rebind_source_fixture_contract(
        previous_path,
        receipt=previous_receipt,
        release_contract=contract(),
        expected_previous_contract_sha256=previous_contract_sha256,
        expected_previous_fixture_sha256=hashlib.sha256(previous_path.read_bytes()).hexdigest(),
        observed_previous_receipt_sha256=hashlib.sha256(previous_receipt_bytes).hexdigest(),
        expected_previous_receipt_sha256=hashlib.sha256(previous_receipt_bytes).hexdigest(),
    )
    rebound_path = tmp_path / "source-fixture.json.gz"
    rebound_path.write_bytes(rebound_bytes)
    rebound_document = json.loads(gzip.decompress(rebound_bytes))

    assert {
        key: value for key, value in original_document.items() if key != "releaseContractSha256"
    } == {key: value for key, value in rebound_document.items() if key != "releaseContractSha256"}
    assert rebound_receipt["sourceArchiveVerifiedForThisWrite"] is False
    assert rebound_receipt["scientificReleaseEligible"] is False
    assert rebound_receipt["contractRebind"]["scientificValuesChanged"] is False
    restored = load_source_fixture(
        rebound_path,
        receipt=rebound_receipt,
        release_contract=contract(),
    )
    assert restored.source_mode == "offline-real-source-fixture"
    assert restored.archive_and_members_verified_this_build is False


def test_contract_rebind_rejects_unauthorized_previous_contract() -> None:
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    with pytest.raises(ScienceContractError, match="authorized previous contract"):
        rebind_source_fixture_contract(
            FIXTURE_DIR / "source-fixture.json.gz",
            receipt=receipt,
            release_contract=contract(),
            expected_previous_contract_sha256="0" * 64,
            expected_previous_fixture_sha256=receipt["sha256"],
            observed_previous_receipt_sha256="0" * 64,
            expected_previous_receipt_sha256="0" * 64,
        )


def test_contract_rebind_rejects_coupled_fixture_and_receipt_mutation(tmp_path: Path) -> None:
    fixture_path = FIXTURE_DIR / "source-fixture.json.gz"
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    document = json.loads(gzip.decompress(fixture_path.read_bytes()))
    document["layers"][0]["lowerMm"][0] += 1
    payload = (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as stream:
        stream.write(payload)
    mutated_path = tmp_path / "mutated.json.gz"
    mutated_path.write_bytes(buffer.getvalue())
    mutated_receipt = dict(receipt)
    mutated_receipt.update(
        {
            "byteSize": mutated_path.stat().st_size,
            "sha256": hashlib.sha256(mutated_path.read_bytes()).hexdigest(),
        }
    )

    with pytest.raises(ScienceContractError, match="authorized previous bytes"):
        rebind_source_fixture_contract(
            mutated_path,
            receipt=mutated_receipt,
            release_contract=contract(),
            expected_previous_contract_sha256=receipt["releaseContractSha256"],
            expected_previous_fixture_sha256=receipt["sha256"],
            observed_previous_receipt_sha256="a" * 64,
            expected_previous_receipt_sha256="a" * 64,
        )


def test_contract_rebind_recovers_after_fixture_publish_before_receipt(
    tmp_path: Path,
) -> None:
    namespace = runpy.run_path(str(REBIND_SCRIPT))
    current_fixture = (FIXTURE_DIR / "source-fixture.json.gz").read_bytes()
    current_receipt = (FIXTURE_DIR / "source-fixture-receipt.json").read_bytes()
    fixture_path = tmp_path / "source-fixture.json.gz"
    receipt_path = tmp_path / "source-fixture-receipt.json"

    fixture_path.write_bytes(current_fixture)
    receipt_path.write_bytes(namespace["_receipt_bytes"](namespace["AUTHORIZED_PREVIOUS_RECEIPT"]))
    namespace["migrate_fixture_pair"](fixture_path, receipt_path, contract())

    assert fixture_path.read_bytes() == current_fixture
    assert receipt_path.read_bytes() == current_receipt
    namespace["migrate_fixture_pair"](fixture_path, receipt_path, contract())
    assert fixture_path.read_bytes() == current_fixture
    assert receipt_path.read_bytes() == current_receipt
