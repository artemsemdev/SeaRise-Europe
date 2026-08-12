"""Public readback must equal subjects freshly verified through Cosign."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import searise_pipeline.supply_chain.public_readback as readback
from searise_pipeline.supply_chain import SupplyChainContractError
from tests.supply_chain.test_candidate_evidence_pair import ROOT, _load, _pair
from tests.supply_chain.test_sigstore_verifier import RUN_ID, _production_envelope, _tool


def _verify(
    tmp_path: Path,
    *,
    fetch: Any | None = None,
    receipt: bool = False,
) -> tuple[readback.PublicReadbackVerification, Path, Path]:
    candidate, evidence = _pair(tmp_path / "pair", data_provenance_class="real-source")
    _production_envelope(evidence)
    tool, lock = _tool(tmp_path)
    roots = {
        "manifest.json": candidate,
        "provenance.intoto.jsonl": evidence,
    }

    def exact(url: str, size: int) -> bytes:
        logical = url.rsplit("/", 1)[1]
        raw = (roots[logical] / logical).read_bytes()
        assert len(raw) == size
        return raw

    result = readback.verify_public_signed_subjects(
        candidate,
        evidence,
        repository_root=ROOT,
        controlled_build_run_id=RUN_ID,
        cosign_executable=tool,
        cosign_tool_lock=lock,
        trusted_cosign_tool_lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        expected_origin="https://downloads.example.test",
        manifest_url="https://downloads.example.test/release/manifest.json",
        provenance_url="https://downloads.example.test/release/provenance.intoto.jsonl",
        receipt_path=(tmp_path / "public-readback.json") if receipt else None,
        observed_at=datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc),
        fetch=fetch or exact,
    )
    return result, candidate, evidence


def test_reverifies_signatures_and_emits_schema_valid_public_receipt(tmp_path: Path) -> None:
    result, candidate, evidence = _verify(tmp_path, receipt=True)
    document = result.receipt
    schema = _load(
        ROOT / "contracts/supply-chain/v1/public-readback-verification-receipt.schema.json"
    )
    Draft202012Validator(schema).validate(document)
    assert (
        result.receipt_bytes
        == (
            json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode()
    )
    assert (tmp_path / "public-readback.json").read_bytes() == result.receipt_bytes
    assert document["observedAt"] == "2026-08-12T02:00:00Z"
    assert [item["path"] for item in document["subjects"]] == [
        "manifest.json",
        "provenance.intoto.jsonl",
    ]
    assert (
        document["subjects"][0]["sha256"]
        == hashlib.sha256((candidate / "manifest.json").read_bytes()).hexdigest()
    )
    assert (
        document["subjects"][1]["sha256"]
        == hashlib.sha256((evidence / "provenance.intoto.jsonl").read_bytes()).hexdigest()
    )
    assert document["claims"] == {
        "cryptographicSubjectsReverified": True,
        "publicBytesMatched": True,
        "productionClaim": False,
        "publicationApproval": False,
        "scientificApproval": False,
    }


@pytest.mark.parametrize("logical", ["manifest.json", "provenance.intoto.jsonl"])
def test_public_byte_tamper_fails_without_receipt(tmp_path: Path, logical: str) -> None:
    def tampered(url: str, size: int) -> bytes:
        fetched = url.rsplit("/", 1)[1]
        root = tmp_path / "pair" / ("candidate" if fetched == "manifest.json" else "evidence")
        raw = bytearray((root / fetched).read_bytes())
        assert len(raw) == size
        if fetched == logical:
            raw[0] ^= 1
        return bytes(raw)

    with pytest.raises(SupplyChainContractError, match="public bytes differ"):
        _verify(tmp_path, fetch=tampered, receipt=True)
    assert not (tmp_path / "public-readback.json").exists()


@pytest.mark.parametrize(
    ("origin", "url"),
    [
        ("http://downloads.example.test", "https://downloads.example.test/release/manifest.json"),
        (
            "https://user@downloads.example.test",
            "https://downloads.example.test/release/manifest.json",
        ),
        (
            "https://downloads.example.test/base",
            "https://downloads.example.test/release/manifest.json",
        ),
        ("https://downloads.example.test", "https://other.example.test/release/manifest.json"),
        (
            "https://downloads.example.test",
            "https://downloads.example.test/release/../manifest.json",
        ),
        (
            "https://downloads.example.test",
            "https://downloads.example.test/release/manifest.json?q=1",
        ),
        (
            "https://downloads.example.test",
            "https://downloads.example.test/release/%6danifest.json",
        ),
        ("https://downloads.example.test", "https://downloads.example.test/release/%zz.json"),
        ("https://downloads.example.test", "https://downloads.example.test/release\\manifest.json"),
        ("https://127.0.0.1", "https://127.0.0.1/release/manifest.json"),
        ("https://localhost", "https://localhost/release/manifest.json"),
        ("https://DOWNLOADS.example.test", "https://downloads.example.test/release/manifest.json"),
        ("https://downloads.example.test/", "https://downloads.example.test/release/manifest.json"),
        ("https://downloads.example.test", "https://downloads.example.test/rélease/manifest.json"),
    ],
)
def test_public_url_boundary_rejects_unsafe_or_different_origins(origin: str, url: str) -> None:
    with pytest.raises(SupplyChainContractError, match="origin|URL|host"):
        normalized = readback._origin(origin)
        readback._subject_url(url, normalized)


def test_existing_receipt_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "public-readback.json"
    path.write_text("preserve\n", encoding="utf-8")
    with pytest.raises(SupplyChainContractError, match="already exists"):
        _verify(tmp_path, receipt=True)
    assert path.read_text(encoding="utf-8") == "preserve\n"


def test_relative_receipt_path_is_rejected_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SupplyChainContractError, match="absolute and canonical"):
        readback._write_new(Path("public-readback.json"), b"{}\n")
    assert not (tmp_path / "public-readback.json").exists()


def test_naive_observation_instant_is_rejected(tmp_path: Path) -> None:
    candidate, evidence = _pair(tmp_path / "pair", data_provenance_class="real-source")
    _production_envelope(evidence)
    tool, lock = _tool(tmp_path)
    roots = {"manifest.json": candidate, "provenance.intoto.jsonl": evidence}

    with pytest.raises(SupplyChainContractError, match="timezone"):
        readback.verify_public_signed_subjects(
            candidate,
            evidence,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            cosign_executable=tool,
            cosign_tool_lock=lock,
            trusted_cosign_tool_lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
            expected_origin="https://downloads.example.test",
            manifest_url="https://downloads.example.test/release/manifest.json",
            provenance_url="https://downloads.example.test/release/provenance.intoto.jsonl",
            observed_at=datetime(2026, 8, 12, 2, 0),
            fetch=lambda url, _size: (
                roots[url.rsplit("/", 1)[1]] / url.rsplit("/", 1)[1]
            ).read_bytes(),
        )
