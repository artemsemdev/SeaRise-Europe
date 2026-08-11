"""Static fail-closed policy tests for protected keyless signing."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github/workflows/phase-1-release-sign.yml"
POLICY = ROOT / "contracts/supply-chain/v1/identity-policy.json"
OPERATIONS = ROOT / "docs/operations/phase-1-protected-signing.md"

CHECKOUT = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
SETUP_PYTHON = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
DOWNLOAD = "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093"
UPLOAD = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
COSIGN_LOCK_SHA256 = "dbc14b1ecc49d3fbbfb907504e50c2c18d398e1c5aa55df1f1002d709c7b70e9"


def _sections(text: str) -> tuple[str, str, str]:
    trigger, jobs = text.split("\npermissions:\n", 1)
    sign, verify = jobs.split("\n  verify:\n", 1)
    return trigger, sign, verify


def _assert_protected_policy(text: str) -> None:
    trigger, sign, verify = _sections(text)
    assert "\n  workflow_dispatch:\n" in trigger
    assert "pull_request" not in trigger
    assert "pull_request_target" not in trigger
    assert "\n  push:" not in trigger

    assert text.count("id-token: write") == 1
    assert "id-token: write" in sign
    assert "id-token: write" not in verify
    assert text.count("environment: phase-1-production-signing") == 1
    assert "environment: phase-1-production-signing" in sign
    assert "environment: phase-1-production-signing" not in verify
    assert "github.event.repository.fork == false" in sign
    assert '[[ "${REPOSITORY_IS_FORK}" == "false" ]]' in sign
    assert "github.repository == 'artemsemdev/SeaRise-Europe'" in sign
    assert "github.ref == 'refs/heads/master'" in sign
    assert (
        "artemsemdev/SeaRise-Europe/.github/workflows/phase-1-release-sign.yml@refs/heads/master"
    ) in sign
    assert '.event == "workflow_dispatch"' in sign
    assert '.path == ".github/workflows/offline-release-controlled.yml"' in sign
    assert ".head_repository.full_name == $repository" in sign
    assert "(.pull_requests | length) == 0" in sign
    assert ".run_attempt == 1" in sign

    action_uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", text, re.MULTILINE)
    assert action_uses
    assert set(action_uses) == {CHECKOUT, SETUP_PYTHON, DOWNLOAD, UPLOAD}
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", item) for item in action_uses)
    assert text.count(DOWNLOAD) == 2
    assert text.count(COSIGN_LOCK_SHA256) == 3
    assert text.count("cosign-linux-amd64") >= 4
    assert text.count("cosign_checksums.txt") >= 4
    assert (text.count("--max-filesize 135178161"), text.count("--max-filesize 3906")) == (2, 2)

    assert "scripts/release/finalize_production_evidence.py" in sign
    assert "Generate deterministic provenance bytes" in sign
    assert "Download original controlled candidate again" in verify
    assert "evidence_artifact_id: ${{ steps.upload-evidence.outputs.artifact-id }}" in sign
    for boundary in (
        "actions/artifacts/${ARTIFACT_ID}/zip",
        "EXPECTED_DIGEST: ${{ needs.sign.outputs.evidence_digest }}",
        "--max-filesize 4194304",
        "sha256sum --check --status",
        "maximum_file_bytes, maximum_total_bytes, root = 1048576, 2097152",
        "set(files) != expected",
    ):
        assert boundary in verify
    assert verify.count("O_NOFOLLOW") == 2 and "bounded_read" in verify
    assert "extractall" not in verify and "rglob" not in verify
    assert "_validate_real_source_unverified_evidence" in verify
    assert verify.count("verify-blob") == 2
    assert "--certificate-identity" in verify
    assert "--certificate-oidc-issuer" in verify
    assert "productionClaim: false" in verify
    assert "publicationClaim: false" in verify
    assert "scientificApproval: false" in verify
    assert "protectedEnvironmentVerified: false" in verify
    assert "publicReadbackPerformed: false" in verify
    assert "gh release" not in text and "gh " not in text
    assert "deploy" not in text.lower()


def test_workflow_enforces_protected_least_privilege_and_clean_verification() -> None:
    _assert_protected_policy(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text.replace("github.event.repository.fork == false", "true", 1),
        lambda text: text.replace("id-token: write", "id-token: read", 1),
        lambda text: text.replace(
            "    permissions:\n      actions: read\n      contents: read\n    steps:",
            "    permissions:\n      actions: read\n      contents: read\n"
            "      id-token: write\n    steps:",
            1,
        ),
        lambda text: text.replace(
            "  workflow_dispatch:\n", "  pull_request:\n  workflow_dispatch:\n", 1
        ),
        lambda text: text.replace(CHECKOUT, "actions/checkout@v4", 1),
        lambda text: text.replace("verify-blob", "version", 1),
        lambda text: text.replace("sha256sum --check --status", "true", 1),
        lambda text: text.replace("set(files) != expected", "False", 1),
        lambda text: text.replace("O_NOFOLLOW", "O_CLOEXEC", 1),
        lambda text: text.replace("--max-filesize 135178161", "--max-filesize 0", 1),
        lambda text: text.replace("productionClaim: false", "productionClaim: true", 1),
    ],
)
def test_security_boundary_tampering_fails_closed(mutation: object) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    with pytest.raises((AssertionError, ValueError)):
        _assert_protected_policy(mutation(text))  # type: ignore[operator]


def test_owner_configuration_matches_reviewed_identity_policy() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    operations = OPERATIONS.read_text(encoding="utf-8")

    assert policy == json.loads(
        '{"$schema":"https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/identity-policy.schema.json","schemaVersion":"1.0.0","contractId":"phase-1-production-signing-identity-v1","repository":"artemsemdev/SeaRise-Europe","workflowPath":".github/workflows/phase-1-release-sign.yml","workflowRef":"refs/heads/master","certificateIdentity":"https://github.com/artemsemdev/SeaRise-Europe/.github/workflows/phase-1-release-sign.yml@refs/heads/master","oidcIssuer":"https://token.actions.githubusercontent.com","protectedEnvironment":"phase-1-production-signing","bundleMediaType":"application/vnd.dev.sigstore.bundle+json;version=0.3"}'
    )  # noqa: E501
    for value in (
        policy["repository"],
        policy["workflowPath"],
        policy["workflowRef"],
        policy["certificateIdentity"],
        policy["oidcIssuer"],
        policy["protectedEnvironment"],
    ):
        assert value in operations
    assert "required reviewer" in operations
    assert "Prevent self-review" in operations
    assert "selected branch `master` only" in operations
    assert "Do not add signing secrets or long-lived keys" in operations
    assert "post-upload" in operations and "readback" in operations
    assert all(
        value in operations
        for value in ("authenticated readers can download", "review evidence, not")
    )
    assert "private Actions artifacts" not in operations
    assert "no real workflow execution is claimed" in operations
    inventory = json.loads((ROOT / "tests/test-inventory.json").read_text(encoding="utf-8"))
    assert any(
        item["path"] == "src/pipeline/tests/supply_chain/test_protected_signing_workflow.py"
        for item in inventory["baselineTests"]
    )
