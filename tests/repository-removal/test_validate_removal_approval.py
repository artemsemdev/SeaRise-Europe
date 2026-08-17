"""Focused unit tests for the repository-removal approval chain."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.repository.validate_removal_approval import (
    DEFAULT_DECISION_SCHEMA,
    DEFAULT_EVIDENCE_SCHEMA,
    DEFAULT_HISTORICAL_ALLOWLIST_SCHEMA,
    DEFAULT_INVENTORY_SCHEMA,
    DEFAULT_VALIDATOR,
    expected_approval_text,
    validate_removal_approval,
)

INVENTORY_PATH = Path("contracts/repository-removal/v1/inventory.json")
EVIDENCE_PATH = Path("contracts/repository-removal/v1/evidence-receipt.json")
DECISION_PATH = Path("contracts/repository-removal/v1/owner-decision.json")
HISTORICAL_ALLOWLIST_PATH = Path(
    "contracts/repository-removal/v1/historical-allowlist.json"
)
INVENTORY_SCHEMA_PATH = Path("contracts/repository-removal/v1/inventory.schema.json")
EVIDENCE_SCHEMA_PATH = Path(
    "contracts/repository-removal/v1/evidence-receipt.schema.json"
)
DECISION_SCHEMA_PATH = Path(
    "contracts/repository-removal/v1/owner-decision.schema.json"
)
HISTORICAL_ALLOWLIST_SCHEMA_PATH = Path(
    "contracts/repository-removal/v1/historical-allowlist.schema.json"
)
VALIDATOR_PATH = Path("scripts/repository/validate_removal_approval.py")
TEST_INVENTORY_PATH = Path("tests/test-inventory.json")
REPLACEMENT_MATRIX_PATH = Path(
    "docs/testing/legacy-frontend-removal-inventory.md"
)


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ApprovalRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._git("init", "-q")
        self._git("config", "user.name", "SeaRise Test")
        self._git("config", "user.email", "test@example.invalid")
        self._write(Path("legacy/runtime.txt"), b"legacy\n")
        self._write(Path("target/runtime.test.ts"), b"target\n")
        for destination, source in (
            (INVENTORY_SCHEMA_PATH, DEFAULT_INVENTORY_SCHEMA),
            (EVIDENCE_SCHEMA_PATH, DEFAULT_EVIDENCE_SCHEMA),
            (DECISION_SCHEMA_PATH, DEFAULT_DECISION_SCHEMA),
            (HISTORICAL_ALLOWLIST_SCHEMA_PATH, DEFAULT_HISTORICAL_ALLOWLIST_SCHEMA),
            (VALIDATOR_PATH, DEFAULT_VALIDATOR),
        ):
            self._write(destination, source.read_bytes())
        self._write(TEST_INVENTORY_PATH, b"test inventory\n")
        self._write(REPLACEMENT_MATRIX_PATH, b"replacement matrix\n")
        self._git("add", ".")
        self._git("commit", "-q", "-m", "test: add audited tree")
        self.audited_commit = self._git("rev-parse", "HEAD").decode().strip()
        self.audited_tree = self._git("rev-parse", "HEAD^{tree}").decode().strip()

    def _git(self, *arguments: str) -> bytes:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=True,
            capture_output=True,
        ).stdout

    def _write(self, path: Path, value: bytes) -> None:
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(value)

    def inventory(self) -> dict[str, Any]:
        legacy_blob = self._git(
            "rev-parse", f"{self.audited_commit}:legacy/runtime.txt"
        ).decode().strip()
        target_blob = self._git(
            "rev-parse", f"{self.audited_commit}:target/runtime.test.ts"
        ).decode().strip()
        return {
            "schemaVersion": "1.0.0",
            "inventoryId": "repository-removal-v1-test",
            "repository": "artemsemdev/SeaRise-Europe",
            "auditedCommit": self.audited_commit,
            "auditedTree": self.audited_tree,
            "createdAt": "2026-08-17T10:00:00Z",
            "governingIssues": [68, 70, 71, 72],
            "candidatePolicy": {
                "candidateV7LocalOnly": True,
                "bytesInspected": False,
                "publicationAuthorized": False,
            },
            "externalResourcePolicy": {
                "mutationAuthorized": False,
                "deferredToSeparateApproval": True,
            },
            "recoveryPolicy": {
                "sourceRecoveryCommit": self.audited_commit,
                "productRollback": "previous-verified-static-pair",
            },
            "items": [
                {
                    "id": "delete-runtime",
                    "kind": "runtime-source",
                    "repositoryPaths": ["legacy/runtime.txt"],
                    "locators": [
                        {
                            "path": "legacy/runtime.txt",
                            "selector": None,
                            "gitBlobSha": legacy_blob,
                        }
                    ],
                    "disposition": "delete-phase-2",
                    "reason": "Static target replaces the legacy runtime.",
                    "ownerIssue": 70,
                    "removalGate": "Static replacement suite passes.",
                    "replacementEvidence": [
                        {
                            "kind": "test-suite",
                            "reference": "target/runtime.test.ts",
                            "invariant": "The static target owns runtime behavior.",
                        }
                    ],
                    "targetOwnerPaths": ["target/runtime.test.ts"],
                    "deferOwner": None,
                    "externalMutationAuthorized": False,
                },
                {
                    "id": "retain-target",
                    "kind": "test",
                    "repositoryPaths": ["target/runtime.test.ts"],
                    "locators": [
                        {
                            "path": "target/runtime.test.ts",
                            "selector": None,
                            "gitBlobSha": target_blob,
                        }
                    ],
                    "disposition": "retain-build-science",
                    "reason": "Permanent static target evidence.",
                    "ownerIssue": None,
                    "removalGate": None,
                    "replacementEvidence": [],
                    "targetOwnerPaths": ["target/runtime.test.ts"],
                    "deferOwner": None,
                    "externalMutationAuthorized": False,
                },
            ],
        }

    def commit_chain(
        self,
        *,
        inventory: dict[str, Any] | None = None,
        include_decision: bool = True,
        evidence_mutation: dict[str, Any] | None = None,
        contract_hash_mutation: dict[str, str] | None = None,
        decision_mutation: dict[str, Any] | None = None,
        historical_entries: list[dict[str, Any]] | None = None,
    ) -> None:
        inventory_bytes = _json_bytes(inventory or self.inventory())
        inventory_sha256 = _sha256(inventory_bytes)
        historical_allowlist_bytes = _json_bytes(
            {
                "schemaVersion": "1.0.0",
                "auditedCommit": self.audited_commit,
                "entries": historical_entries or [],
            }
        )
        contract_hash_inputs = {
            "inventorySchemaSha256": self._git(
                "show", f"HEAD:{INVENTORY_SCHEMA_PATH}"
            ),
            "evidenceReceiptSchemaSha256": self._git(
                "show", f"HEAD:{EVIDENCE_SCHEMA_PATH}"
            ),
            "ownerDecisionSchemaSha256": self._git(
                "show", f"HEAD:{DECISION_SCHEMA_PATH}"
            ),
            "historicalAllowlistSchemaSha256": self._git(
                "show", f"HEAD:{HISTORICAL_ALLOWLIST_SCHEMA_PATH}"
            ),
            "validatorSha256": self._git("show", f"HEAD:{VALIDATOR_PATH}"),
            "testInventorySha256": self._git("show", f"HEAD:{TEST_INVENTORY_PATH}"),
            "historicalAllowlistSha256": historical_allowlist_bytes,
            "replacementMatrixSha256": self._git(
                "show", f"HEAD:{REPLACEMENT_MATRIX_PATH}"
            ),
        }
        evidence: dict[str, Any] = {
            "schemaVersion": "1.0.0",
            "receiptId": "repository-removal-evidence-v1-test",
            "auditedCommit": self.audited_commit,
            "auditedTree": self.audited_tree,
            "inventorySha256": inventory_sha256,
            "contractHashes": {
                field: _sha256(value) for field, value in contract_hash_inputs.items()
            },
            "recordedAt": "2026-08-17T10:05:00Z",
            "cleanClone": True,
            "browserDisposition": {
                "required": "chromium",
                "firefox": "deferred",
                "webkit": "optional-historical-evidence",
                "threeBrowserSupportClaim": False,
            },
            "candidateIsolation": {
                "candidateV7BytesUsed": False,
                "tarBytesUsed": False,
                "uploaded": False,
            },
            "externalResourceMutation": False,
            "checks": [
                {
                    "id": "static-target",
                    "command": "npm run web:check",
                    "result": "passed",
                    "outputSha256": "1" * 64,
                    "evidencePaths": ["target/runtime.test.ts"],
                }
            ],
        }
        if contract_hash_mutation:
            evidence["contractHashes"].update(contract_hash_mutation)
        if evidence_mutation:
            evidence.update(evidence_mutation)
        evidence_bytes = _json_bytes(evidence)

        self._write(INVENTORY_PATH, inventory_bytes)
        self._write(EVIDENCE_PATH, evidence_bytes)
        self._write(HISTORICAL_ALLOWLIST_PATH, historical_allowlist_bytes)
        paths = [
            str(INVENTORY_PATH),
            str(EVIDENCE_PATH),
            str(HISTORICAL_ALLOWLIST_PATH),
        ]
        if include_decision:
            decision: dict[str, Any] = {
                "schemaVersion": "1.0.0",
                "decisionId": "repository-removal-owner-decision-v1-test",
                "decision": "approved",
                "approvedBy": "project-owner",
                "approvedAt": "2026-08-17T10:10:00Z",
                "auditedCommit": self.audited_commit,
                "inventorySha256": inventory_sha256,
                "evidenceReceiptSha256": _sha256(evidence_bytes),
                "approvalText": expected_approval_text(
                    self.audited_commit,
                    inventory_sha256,
                    _sha256(evidence_bytes),
                ),
                "approvalSource": {
                    "issue": 68,
                    "commentId": 12345,
                    "commentUrl": (
                        "https://github.com/artemsemdev/SeaRise-Europe/issues/68"
                        "#issuecomment-12345"
                    ),
                    "author": "artemsemdev",
                    "authorAssociation": "OWNER",
                    "bodySha256": _sha256(
                        expected_approval_text(
                            self.audited_commit,
                            inventory_sha256,
                            _sha256(evidence_bytes),
                        ).encode("utf-8")
                    ),
                },
                "authorizedIssues": [70, 71, 72],
                "candidatePublicationAuthorized": False,
                "externalResourceMutationAuthorized": False,
            }
            if decision_mutation:
                decision.update(decision_mutation)
            self._write(DECISION_PATH, _json_bytes(decision))
            paths.append(str(DECISION_PATH))
        self._git("add", *paths)
        self._git("commit", "-q", "-m", "test: add approval chain")


class RemovalApprovalTests(unittest.TestCase):
    def _validate(
        self, repository: ApprovalRepository, *, allow_unapproved: bool = False
    ) -> list[str]:
        return validate_removal_approval(
            repository_root=repository.root,
            inventory_path=INVENTORY_PATH,
            evidence_path=EVIDENCE_PATH,
            decision_path=DECISION_PATH,
            historical_allowlist_path=HISTORICAL_ALLOWLIST_PATH,
            inventory_schema_path=INVENTORY_SCHEMA_PATH,
            evidence_schema_path=EVIDENCE_SCHEMA_PATH,
            decision_schema_path=DECISION_SCHEMA_PATH,
            historical_allowlist_schema_path=HISTORICAL_ALLOWLIST_SCHEMA_PATH,
            validator_path=VALIDATOR_PATH,
            test_inventory_path=TEST_INVENTORY_PATH,
            replacement_matrix_path=REPLACEMENT_MATRIX_PATH,
            allow_unapproved=allow_unapproved,
        )

    def test_accepts_exact_committed_approval_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain()

            errors = self._validate(repository)

        self.assertEqual(errors, [])

    def test_requires_decision_unless_preapproval_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(include_decision=False)

            errors = self._validate(repository)
            preapproval_errors = self._validate(repository, allow_unapproved=True)

        self.assertIn(
            "owner decision is absent; use --allow-unapproved only for "
            "pre-approval inventory validation",
            errors,
        )
        self.assertEqual(preapproval_errors, [])

    def test_uses_committed_bytes_not_dirty_worktree_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain()
            repository._write(INVENTORY_PATH, b"not the committed inventory\n")

            errors = self._validate(repository)

        self.assertEqual(errors, [])

    def test_rejects_path_present_only_after_audited_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            inventory = repository.inventory()
            inventory["items"][0]["targetOwnerPaths"] = ["target/late.test.ts"]
            repository._write(Path("target/late.test.ts"), b"late\n")
            repository._git("add", "target/late.test.ts")
            repository.commit_chain(inventory=inventory)

            errors = self._validate(repository)

        self.assertIn(
            "targetOwnerPaths not tracked at audited commit: ['target/late.test.ts']",
            errors,
        )

    def test_rejects_unsorted_and_globally_duplicate_inventory_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            inventory = repository.inventory()
            inventory["items"].reverse()
            inventory["items"][0]["repositoryPaths"] = [
                "target/runtime.test.ts",
                "legacy/runtime.txt",
            ]
            inventory["items"][1]["repositoryPaths"] = ["legacy/runtime.txt"]
            repository.commit_chain(inventory=inventory)

            errors = self._validate(repository)

        self.assertIn("inventory items must be sorted by id", errors)
        self.assertIn("retain-target: repositoryPaths must be sorted", errors)
        self.assertIn(
            "repositoryPaths assigned to multiple items: ['legacy/runtime.txt']",
            errors,
        )
        self.assertIn("retain-target: locator paths must equal repositoryPaths", errors)

    def test_rejects_contract_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(
                contract_hash_mutation={"validatorSha256": "0" * 64}
            )

            errors = self._validate(repository)

        self.assertIn(
            "evidence receipt validatorSha256 does not match committed bytes",
            errors,
        )

    def test_rejects_duplicate_check_ids_and_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            duplicate_check = {
                "id": "static-target",
                "command": "npm run web:test",
                "result": "passed",
                "outputSha256": "2" * 64,
                "evidencePaths": ["target/runtime.test.ts"],
            }
            repository.commit_chain(
                evidence_mutation={
                    "inventorySha256": "0" * 64,
                    "checks": [duplicate_check, duplicate_check],
                }
            )

            errors = self._validate(repository)

        self.assertIn(
            "evidence receipt inventorySha256 does not match committed inventory",
            errors,
        )
        self.assertIn("duplicate evidence check ids: ['static-target']", errors)

    def test_rejects_audited_tree_and_locator_blob_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            inventory = repository.inventory()
            inventory["auditedTree"] = "0" * 40
            inventory["items"][0]["locators"][0]["gitBlobSha"] = "0" * 40
            repository.commit_chain(inventory=inventory)

            errors = self._validate(repository)

        self.assertIn("inventory auditedTree does not match audited commit tree", errors)
        self.assertIn(
            "delete-runtime: locator gitBlobSha does not match audited blob for "
            "legacy/runtime.txt",
            errors,
        )

    def test_rejects_allowlist_path_without_historical_inventory_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(
                historical_entries=[
                    {
                        "id": "legacy-runtime-term",
                        "path": "legacy/runtime.txt",
                        "rule": "historical-adr-term",
                        "reason": "Test exact-path classification.",
                        "activeRuntimeAllowed": False,
                    }
                ]
            )

            errors = self._validate(repository)

        self.assertIn(
            "historical allowlist paths must be classified "
            "retain-historical-evidence in inventory",
            errors,
        )

    def test_rejects_approval_source_body_and_comment_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(
                decision_mutation={
                    "approvalSource": {
                        "issue": 68,
                        "commentId": 999,
                        "commentUrl": (
                            "https://github.com/artemsemdev/SeaRise-Europe/issues/68"
                            "#issuecomment-123"
                        ),
                        "author": "artemsemdev",
                        "authorAssociation": "OWNER",
                        "bodySha256": "0" * 64,
                    }
                }
            )

            errors = self._validate(repository)

        self.assertIn(
            "owner decision approvalSource bodySha256 does not match approvalText",
            errors,
        )
        self.assertIn(
            "owner decision approvalSource commentId does not match commentUrl",
            errors,
        )

    def test_rejects_nonexact_owner_approval_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(decision_mutation={"approvalText": "Approved."})

            errors = self._validate(repository)

        self.assertIn(
            "owner decision approvalText is not the exact required approval",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
