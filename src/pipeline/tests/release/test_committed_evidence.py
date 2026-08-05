from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
INDEX = (
    ROOT
    / "src/pipeline/science/evidence/ar6-regional-release-evidence.json"
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_committed_mac_evidence_bundle_matches_its_index() -> None:
    evidence = _load(INDEX)
    bundle = evidence["committedEvidenceBundle"]
    root = ROOT / bundle["path"]

    for relative_path, expected in bundle["files"].items():
        actual = hashlib.sha256((root / relative_path).read_bytes()).hexdigest()
        assert actual == expected

    assert evidence["automatedValidation"] == "pending"
    assert evidence["releaseDisposition"] == "pending-owner"
    assert evidence["phase1Unlocked"] is False
    assert _load(root / "manifest.json")["artifacts"].__len__() == 31
    assert _load(root / "gate.json")["phase1Unlocked"] is False
    assert _load(root / "delivery-measurements.json")["status"] == "passed"
