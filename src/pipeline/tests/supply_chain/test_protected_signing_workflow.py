"""Static fail-closed policy tests for protected keyless evidence orchestration."""

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


def _jobs(text: str) -> dict[str, str]:
    starts = list(re.finditer(r"^  (intake|sign|finalize|verify):$", text, re.MULTILINE))
    assert [match.group(1) for match in starts] == ["intake", "sign", "finalize", "verify"]
    return {
        match.group(1): text[match.start() : starts[index + 1].start()]
        if index + 1 < len(starts)
        else text[match.start() :]
        for index, match in enumerate(starts)
    }


def _assert_protected_policy(text: str) -> None:
    jobs = _jobs(text)
    trigger = text[: text.index("\npermissions:\n")]
    intake, sign, finalize, verify = (jobs[name] for name in jobs)

    assert "\n  workflow_dispatch:\n" in trigger
    assert all(
        event not in trigger for event in ("pull_request", "pull_request_target", "\n  push:")
    )
    assert text.count("id-token: write") == 1
    assert "id-token: write" in sign
    assert all("id-token: write" not in job for job in (intake, finalize, verify))
    assert text.count("environment: phase-1-production-signing") == 1
    assert "environment: phase-1-production-signing" in sign
    assert all(
        "environment: phase-1-production-signing" not in job for job in (intake, finalize, verify)
    )

    for job in (intake, sign):
        assert "github.repository == 'artemsemdev/SeaRise-Europe'" in job
        assert "github.repository_id == '1196432661'" in job
        assert "github.event.repository.fork == false" in job
        assert "github.ref == 'refs/heads/master'" in job
        assert '[[ "${GITHUB_RUN_ATTEMPT}" == "1" ]]' in job
        assert (
            "artemsemdev/SeaRise-Europe/.github/workflows/phase-1-release-sign.yml@refs/heads/master"
            in job
        )

    action_uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", text, re.MULTILINE)
    assert set(action_uses) == {CHECKOUT, SETUP_PYTHON, DOWNLOAD, UPLOAD}
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", item) for item in action_uses)
    assert (text.count(CHECKOUT), text.count(SETUP_PYTHON)) == (4, 4)
    assert (text.count(DOWNLOAD), text.count(UPLOAD)) == (3, 4)

    assert intake.count("protected-candidate-authority") == 1
    assert intake.count("protected-candidate-extract") == 1
    assert "actions/artifacts/${artifact_id}/zip" in intake
    assert "scripts/release/validate_candidate_bytes.py" in intake
    assert "id-token" not in intake
    assert "Generate deterministic signing provenance without OIDC permission" in intake

    assert sign.count("sign-blob") == 2
    assert sign.count("verify-blob") == 0
    assert "cmp --silent" in sign
    assert "scripts/release/validate_candidate_bytes.py" in sign
    assert sign.count(COSIGN_LOCK_SHA256) == 2
    assert "manifest.sigstore.json" in sign and "provenance.sigstore.json" in sign

    assert "needs:\n      - intake\n      - sign" in finalize
    assert "id-token" not in finalize
    assert finalize.count("scripts/release/finalize_production_evidence.py") == 1
    for flag in (
        "--candidate-root",
        "--repository-root",
        "--controlled-build-run-id",
        "--manifest-bundle",
        "--provenance-bundle",
        "--output-root",
    ):
        assert flag in finalize
    assert "umask 077" in finalize
    assert 'mkdir -m 0700 "${finalizer_root}"' in finalize
    assert 'mkdir -m 0700 "${snapshot_parent}" "${output_parent}"' in finalize
    assert finalize.count("stat -c '%a'") == 2
    assert finalize.count("stat -c '%u'") == 2
    assert '[[ "${finalizer_root}" == /* ]]' in finalize
    assert '[[ "${snapshot_parent}" != "${GITHUB_WORKSPACE}"* ]]' in finalize
    assert '[[ "${snapshot_parent}" != "${RUNNER_TEMP}/prepared-inputs"* ]]' in finalize
    assert '[[ "${output_parent}" != "${GITHUB_WORKSPACE}"* ]]' in finalize
    assert '[[ "${output_parent}" != "${RUNNER_TEMP}/prepared-inputs"* ]]' in finalize
    assert 'test ! -e "${evidence_root}"' in finalize
    assert 'RUNNER_TEMP="${snapshot_parent}" \\' in finalize
    assert 'PYTHONPATH=src/pipeline "${RUNNER_TEMP}/finalize-venv/bin/python"' in finalize
    assert finalize.count('RUNNER_TEMP="${snapshot_parent}"') == 1
    assert "env:\n          RUNNER_TEMP:" not in finalize
    exact_leaf = "${{ runner.temp }}/production-evidence-finalizer/output/evidence"
    assert f"path: {exact_leaf}" in finalize
    assert "path: ${{ runner.temp }}/production-evidence-finalizer/output\n" not in finalize

    assert verify.count("protected-candidate-authority") == 1
    assert verify.count("protected-candidate-extract") == 1
    assert verify.count("protected-evidence-extract") == 1
    assert verify.count("verify-blob") == 2
    assert verify.count("sign-blob") == 0
    assert verify.count(COSIGN_LOCK_SHA256) == 1
    assert "EXPECTED_DIGEST: ${{ needs.finalize.outputs.evidence_digest }}" in verify
    assert "ARTIFACT_ID: ${{ needs.finalize.outputs.evidence_artifact_id }}" in verify
    assert "actions/artifacts/${ARTIFACT_ID}/zip" in verify
    assert "_validate_real_source_unverified_evidence" in verify
    assert "--certificate-identity" in verify and "--certificate-oidc-issuer" in verify

    assert text.count("scripts/release/finalize_production_evidence.py") == 1
    assert "gh release" not in text and "gh " not in text
    assert "publicReadbackPerformed: false" in verify
    assert "protectedEnvironmentVerified: false" in verify
    assert "productionClaim: false" in verify
    assert "publicationClaim: false" in verify
    assert "scientificApproval: false" in verify


def test_workflow_enforces_four_plane_least_privilege_and_exact_evidence() -> None:
    _assert_protected_policy(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text.replace("github.event.repository.fork == false", "true", 1),
        lambda text: text.replace("id-token: write", "id-token: read", 1),
        lambda text: text.replace("github.repository_id == '1196432661'", "true", 1),
        lambda text: text.replace(
            "  workflow_dispatch:\n", "  pull_request:\n  workflow_dispatch:\n", 1
        ),
        lambda text: text.replace(CHECKOUT, "actions/checkout@v4", 1),
        lambda text: text.replace("cmp --silent", "true", 1),
        lambda text: text.replace(
            'mkdir -m 0700 "${finalizer_root}"', 'mkdir -p "${finalizer_root}"', 1
        ),
        lambda text: text.replace('test ! -e "${evidence_root}"', "true", 1),
        lambda text: text.replace('RUNNER_TEMP="${snapshot_parent}" \\', "", 1),
        lambda text: text.replace(
            "path: ${{ runner.temp }}/production-evidence-finalizer/output/evidence",
            "path: ${{ runner.temp }}/production-evidence-finalizer/output",
            1,
        ),
        lambda text: text.replace("protected-evidence-extract", "true", 1),
        lambda text: text.replace("verify-blob", "version", 1),
        lambda text: text.replace("publicReadbackPerformed: false", "true", 1),
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
    assert "four jobs" in operations
    assert "public readback" in operations
    assert "no real workflow execution is claimed" in operations
    inventory = json.loads((ROOT / "tests/test-inventory.json").read_text(encoding="utf-8"))
    assert any(
        item["path"] == "src/pipeline/tests/supply_chain/test_protected_signing_workflow.py"
        for item in inventory["baselineTests"]
    )
