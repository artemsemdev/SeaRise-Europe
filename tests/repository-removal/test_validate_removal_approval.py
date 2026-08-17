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
    DEFAULT_CENSUS,
    DEFAULT_CENSUS_SCHEMA,
    DEFAULT_CHECK_OUTPUT_SCHEMA,
    DEFAULT_DECISION_SCHEMA,
    DEFAULT_EVIDENCE_SCHEMA,
    DEFAULT_HISTORICAL_ALLOWLIST_SCHEMA,
    DEFAULT_INVENTORY_SCHEMA,
    DEFAULT_VALIDATOR,
    RemovalApprovalError,
    _canonical_census,
    _selector_count,
    _tracked_blobs,
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
CENSUS_PATH = Path("contracts/repository-removal/v1/census.json")
CENSUS_SCHEMA_PATH = Path("contracts/repository-removal/v1/census.schema.json")
CHECK_OUTPUT_SCHEMA_PATH = Path(
    "contracts/repository-removal/v1/check-output.schema.json"
)
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
    "docs/testing/legacy-runtime-removal-matrix.md"
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
        self._write(Path("historical/evidence.md"), b"historical evidence\n")
        self._write(Path("target/runtime.test.ts"), b"target\n")
        self._write(Path(".github/workflows/ci.yml"), b"jobs:\n  frontend:\n    runs-on: ubuntu-latest\n")
        self._write(Path("scripts/ci/routes.py"), b"FRONTEND = ('src/frontend/**',)\n")
        for destination, source in (
            (INVENTORY_SCHEMA_PATH, DEFAULT_INVENTORY_SCHEMA),
            (CENSUS_SCHEMA_PATH, DEFAULT_CENSUS_SCHEMA),
            (CHECK_OUTPUT_SCHEMA_PATH, DEFAULT_CHECK_OUTPUT_SCHEMA),
            (EVIDENCE_SCHEMA_PATH, DEFAULT_EVIDENCE_SCHEMA),
            (DECISION_SCHEMA_PATH, DEFAULT_DECISION_SCHEMA),
            (HISTORICAL_ALLOWLIST_SCHEMA_PATH, DEFAULT_HISTORICAL_ALLOWLIST_SCHEMA),
            (VALIDATOR_PATH, DEFAULT_VALIDATOR),
        ):
            self._write(destination, source.read_bytes())
        self._write(
            CENSUS_PATH,
            _json_bytes(
                {
                    "schemaVersion": "1.0.0",
                    "censusId": "phase-2-legacy-runtime-v1",
                    "issues": [
                        {
                            "ownerIssue": 70,
                            "allowedReplacementSuiteIds": ["target-suite"],
                            "requiredReplacementSuiteIds": ["target-suite"],
                            "roots": [],
                            "paths": ["legacy/runtime.txt"],
                            "selectors": [],
                        },
                        {
                            "ownerIssue": 71,
                            "allowedReplacementSuiteIds": [],
                            "requiredReplacementSuiteIds": [],
                            "roots": [],
                            "paths": [],
                            "selectors": [],
                        },
                        {
                            "ownerIssue": 72,
                            "allowedReplacementSuiteIds": [],
                            "requiredReplacementSuiteIds": [],
                            "roots": [],
                            "paths": [],
                            "selectors": [],
                        },
                    ],
                }
            ),
        )
        self._write(
            TEST_INVENTORY_PATH,
            _json_bytes(
                {
                    "suites": [
                        {
                            "id": "legacy-suite",
                            "status": "active",
                            "replacementGate": {"issue": 70},
                        },
                        {
                            "id": "target-suite",
                            "status": "active",
                            "sourcePaths": ["target/**/*.test.ts"],
                            "commands": {
                                "focused": "npm run web:check",
                                "full": "npm run web:check && npm run web:e2e",
                            },
                            "replacementGate": {"issue": None},
                        },
                        {
                            "id": "other-issue-suite",
                            "status": "active",
                            "sourcePaths": ["target/**/*.test.ts"],
                            "commands": {
                                "focused": "npm run web:check",
                                "full": "npm run web:check && npm run web:e2e",
                            },
                            "replacementGate": {"issue": None},
                        },
                    ],
                    "baselineTests": [
                        {"path": "legacy/runtime.txt", "suite": "legacy-suite"}
                    ],
                }
            ),
        )
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
        historical_blob = self._git(
            "rev-parse", f"{self.audited_commit}:historical/evidence.md"
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
                            "reference": "target-suite",
                            "invariant": "The static target owns runtime behavior.",
                        }
                    ],
                    "replacementSuiteIds": ["target-suite"],
                    "replacementCheckIds": ["static-target"],
                    "retirementSuiteIds": ["legacy-suite"],
                    "targetOwnerPaths": ["target/runtime.test.ts"],
                    "deferOwner": None,
                    "historicalAllowlistEntry": None,
                    "externalMutationAuthorized": False,
                },
                {
                    "id": "retain-historical",
                    "kind": "contract-fixture-evidence",
                    "locators": [
                        {
                            "path": "historical/evidence.md",
                            "selector": None,
                            "gitBlobSha": historical_blob,
                        }
                    ],
                    "disposition": "retain-historical-evidence",
                    "reason": "Immutable historical evidence remains auditable.",
                    "ownerIssue": None,
                    "removalGate": None,
                    "replacementEvidence": [],
                    "replacementSuiteIds": [],
                    "replacementCheckIds": [],
                    "retirementSuiteIds": [],
                    "targetOwnerPaths": [],
                    "deferOwner": None,
                    "historicalAllowlistEntry": "historical-evidence",
                    "externalMutationAuthorized": False,
                },
                {
                    "id": "retain-target",
                    "kind": "test",
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
                    "replacementSuiteIds": [],
                    "replacementCheckIds": [],
                    "retirementSuiteIds": [],
                    "targetOwnerPaths": ["target/runtime.test.ts"],
                    "deferOwner": None,
                    "historicalAllowlistEntry": None,
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
        check_mutation: dict[str, Any] | None = None,
        check_output_mutation: dict[str, Any] | None = None,
        contract_hash_mutation: dict[str, str] | None = None,
        decision_mutation: dict[str, Any] | None = None,
        historical_entries: list[dict[str, Any]] | None = None,
    ) -> None:
        inventory_bytes = _json_bytes(inventory or self.inventory())
        inventory_sha256 = _sha256(inventory_bytes)
        historical_blob = self._git(
            "rev-parse", f"{self.audited_commit}:historical/evidence.md"
        ).decode().strip()
        default_historical_entries = [
            {
                "id": "historical-evidence",
                "path": "historical/evidence.md",
                "gitBlobSha": historical_blob,
                "rule": "historical-adr-term",
                "reason": "Test exact-path historical classification.",
                "activeRuntimeAllowed": False,
            }
        ]
        historical_allowlist_bytes = _json_bytes(
            {
                "schemaVersion": "1.0.0",
                "auditedCommit": self.audited_commit,
                "auditedTree": self.audited_tree,
                "entries": (
                    historical_entries
                    if historical_entries is not None
                    else default_historical_entries
                ),
            }
        )
        contract_hash_inputs = {
            "inventorySchemaSha256": self._git(
                "show", f"HEAD:{INVENTORY_SCHEMA_PATH}"
            ),
            "censusSha256": self._git("show", f"HEAD:{CENSUS_PATH}"),
            "censusSchemaSha256": self._git(
                "show", f"HEAD:{CENSUS_SCHEMA_PATH}"
            ),
            "checkOutputSchemaSha256": self._git(
                "show", f"HEAD:{CHECK_OUTPUT_SCHEMA_PATH}"
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
        check_output: dict[str, Any] = {
            "schemaVersion": "1.0.0",
            "auditedCommit": self.audited_commit,
            "checkId": "static-target",
            "command": "npm run web:check",
            "result": "passed",
        }
        if check_output_mutation:
            check_output.update(check_output_mutation)
        check_output_bytes = _json_bytes(check_output)
        output_path = Path(
            "tests/evidence/repository-removal/v1/static-target.json"
        )
        check: dict[str, Any] = {
            "id": "static-target",
            "command": "npm run web:check",
            "result": "passed",
            "outputPath": str(output_path),
            "outputSha256": _sha256(check_output_bytes),
            "coveredReplacementSuiteIds": ["target-suite"],
            "coveredTargetOwnerPaths": ["target/runtime.test.ts"],
            "evidencePaths": [
                "target/runtime.test.ts",
                str(output_path),
            ],
        }
        if check_mutation:
            check.update(check_mutation)
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
            "checks": [check],
        }
        if contract_hash_mutation:
            evidence["contractHashes"].update(contract_hash_mutation)
        if evidence_mutation:
            evidence.update(evidence_mutation)
        evidence_bytes = _json_bytes(evidence)

        self._write(INVENTORY_PATH, inventory_bytes)
        self._write(EVIDENCE_PATH, evidence_bytes)
        self._write(HISTORICAL_ALLOWLIST_PATH, historical_allowlist_bytes)
        self._write(output_path, check_output_bytes)
        paths = [
            str(INVENTORY_PATH),
            str(EVIDENCE_PATH),
            str(HISTORICAL_ALLOWLIST_PATH),
            str(output_path),
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
                "liveVerificationRequired": True,
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
    def test_repository_census_resolves_every_canonical_locator(self) -> None:
        root = Path(__file__).resolve().parents[2]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        census = json.loads(DEFAULT_CENSUS.read_text(encoding="utf-8"))

        owners, errors = _canonical_census(
            census,
            repository_root=root,
            audited_commit=commit,
            tracked=_tracked_blobs(root, commit),
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            {issue: sum(owner == issue for owner in owners.values()) for issue in (70, 71, 72)},
            {70: 109, 71: 107, 72: 13},
        )
        test_inventory = json.loads(
            (root / "tests/test-inventory.json").read_text(encoding="utf-8")
        )
        active_suites = {
            suite["id"]
            for suite in test_inventory["suites"]
            if suite.get("status") == "active"
        }
        for issue in census["issues"]:
            allowed = set(issue["allowedReplacementSuiteIds"])
            required = set(issue["requiredReplacementSuiteIds"])
            self.assertLessEqual(required, allowed)
            self.assertLessEqual(allowed, active_suites)
        issue71 = next(issue for issue in census["issues"] if issue["ownerIssue"] == 71)
        self.assertIn(
            "pipeline-science-contracts",
            issue71["requiredReplacementSuiteIds"],
        )

    def _validate(
        self,
        repository: ApprovalRepository,
        *,
        allow_unapproved: bool = False,
        live_comment_mutation: dict[str, Any] | None = None,
        verify_owner_comment: bool = True,
    ) -> list[str]:
        def owner_comment(comment_id: int) -> dict[str, Any]:
            decision = json.loads(
                repository._git("show", f"HEAD:{DECISION_PATH}")
            )
            comment = {
                "id": comment_id,
                "html_url": decision["approvalSource"]["commentUrl"],
                "issue_url": (
                    "https://api.github.com/repos/artemsemdev/"
                    "SeaRise-Europe/issues/68"
                ),
                "body": decision["approvalText"],
                "author_association": "OWNER",
                "user": {"login": "artemsemdev"},
            }
            if live_comment_mutation:
                comment.update(live_comment_mutation)
            return comment

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
            census_path=CENSUS_PATH,
            census_schema_path=CENSUS_SCHEMA_PATH,
            check_output_schema_path=CHECK_OUTPUT_SCHEMA_PATH,
            validator_path=VALIDATOR_PATH,
            test_inventory_path=TEST_INVENTORY_PATH,
            replacement_matrix_path=REPLACEMENT_MATRIX_PATH,
            allow_unapproved=allow_unapproved,
            verify_owner_comment=verify_owner_comment and not allow_unapproved,
            owner_comment_fetcher=owner_comment,
        )

    @staticmethod
    def _commit_census(repository: ApprovalRepository, census: dict[str, Any]) -> None:
        repository._write(CENSUS_PATH, _json_bytes(census))
        repository._git("add", str(CENSUS_PATH))
        repository._git("commit", "-q", "-m", "test: update census")

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

    def test_rejects_unsorted_and_globally_duplicate_locator_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            inventory = repository.inventory()
            inventory["items"].reverse()
            inventory["items"][0]["locators"] = inventory["items"][2]["locators"]
            repository.commit_chain(inventory=inventory)

            errors = self._validate(repository)

        self.assertIn("inventory items must be sorted by id", errors)
        self.assertIn("locator path/selector pairs assigned to multiple items", errors)

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
                "outputPath": "tests/evidence/repository-removal/v1/static-target.json",
                "outputSha256": "2" * 64,
                "coveredReplacementSuiteIds": ["target-suite"],
                "coveredTargetOwnerPaths": ["target/runtime.test.ts"],
                "evidencePaths": [
                    "target/runtime.test.ts",
                    "tests/evidence/repository-removal/v1/static-target.json",
                ],
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
                        "gitBlobSha": repository._git(
                            "rev-parse",
                            f"{repository.audited_commit}:legacy/runtime.txt",
                        ).decode().strip(),
                        "rule": "historical-adr-term",
                        "reason": "Test exact-path classification.",
                        "activeRuntimeAllowed": False,
                    }
                ]
            )

            errors = self._validate(repository)

        self.assertIn(
            "historical allowlist entries must exactly match inventory "
            "retain-historical-evidence cross-links",
            errors,
        )

    def test_rejects_unsafe_evidence_command_and_untracked_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(
                evidence_mutation={
                    "checks": [
                        {
                            "id": "unsafe-check",
                            "command": "gh secret delete TOKEN",
                            "result": "passed",
                            "outputPath": (
                                "tests/evidence/repository-removal/v1/unsafe-check.json"
                            ),
                            "outputSha256": "2" * 64,
                            "coveredReplacementSuiteIds": ["target-suite"],
                            "coveredTargetOwnerPaths": ["target/runtime.test.ts"],
                            "evidencePaths": [
                                "missing/evidence.ts",
                                "target/runtime.test.ts",
                                "tests/evidence/repository-removal/v1/unsafe-check.json",
                            ],
                        }
                    ]
                }
            )

            errors = self._validate(repository)

        self.assertIn(
            "unsafe-check: evidence command is not read-only and local-safe", errors
        )
        self.assertIn(
            "unsafe-check: evidencePaths not tracked at audited commit: "
            "['missing/evidence.ts']",
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

    def test_rejects_non_exhaustive_canonical_census_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            census = json.loads((repository.root / CENSUS_PATH).read_text())
            census["issues"][0]["paths"].insert(0, "historical/evidence.md")
            self._commit_census(repository, census)
            repository.commit_chain()

            errors = self._validate(repository)

        self.assertTrue(
            any("delete inventory does not exhaust canonical census" in error for error in errors),
            errors,
        )

    def test_rejects_missing_and_duplicate_canonical_selectors(self) -> None:
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as directory:
                repository = ApprovalRepository(Path(directory))
                selector_value = "frontend" if duplicate else "missing"
                if duplicate:
                    repository._write(
                        Path(".github/workflows/ci.yml"),
                        b"jobs:\n  frontend:\n    runs-on: ubuntu-latest\n  frontend:\n    runs-on: ubuntu-latest\n",
                    )
                    repository._git("add", ".github/workflows/ci.yml")
                    repository._git("commit", "-q", "-m", "test: duplicate selector")
                    repository.audited_commit = repository._git(
                        "rev-parse", "HEAD"
                    ).decode().strip()
                    repository.audited_tree = repository._git(
                        "rev-parse", "HEAD^{tree}"
                    ).decode().strip()
                census = json.loads((repository.root / CENSUS_PATH).read_text())
                census["issues"][0]["selectors"] = [
                    {
                        "path": ".github/workflows/ci.yml",
                        "kind": "workflow-job",
                        "value": selector_value,
                    }
                ]
                self._commit_census(repository, census)
                inventory = repository.inventory()
                workflow_blob = repository._git(
                    "rev-parse",
                    f"{repository.audited_commit}:.github/workflows/ci.yml",
                ).decode().strip()
                inventory["items"][0]["locators"].insert(
                    0,
                    {
                        "path": ".github/workflows/ci.yml",
                        "selector": f"workflow-job:{selector_value}",
                        "gitBlobSha": workflow_blob,
                    },
                )
                repository.commit_chain(inventory=inventory)

                errors = self._validate(repository)

            self.assertTrue(
                any("canonical selector must exist exactly once" in error for error in errors),
                errors,
            )

    def test_setuptools_mapping_selectors_are_structural_and_independent(self) -> None:
        source = b'''[tool.setuptools]\npackages = ["pipeline", "searise_pipeline"]\n\n[tool.setuptools.package-dir]\npipeline = "."\nsearise_pipeline = "searise_pipeline"\n'''

        self.assertEqual(_selector_count("setuptools-package", "pipeline", source), 1)
        self.assertEqual(
            _selector_count("setuptools-package-dir", "pipeline", source),
            1,
        )
        self.assertEqual(
            _selector_count("setuptools-package", "missing", source),
            0,
        )

    def test_pyproject_dependency_ignores_metadata_and_unrelated_toml(self) -> None:
        source = b'''[project]\nname = "demo"\ndescription = "azure-storage-blob"\ndependencies = []\n\n[tool.demo]\npackage = "azure-storage-blob"\n'''

        self.assertEqual(
            _selector_count("pyproject-dependency", "azure-storage-blob", source),
            0,
        )

    def test_pyproject_dependency_parses_main_and_optional_pep508_entries(self) -> None:
        source = b'''[project]\nname = "demo"\ndependencies = ["Azure_Storage.Blob[crypto]>=12; python_version >= '3.11'"]\n\n[project.optional-dependencies]\ndatabase = ["Psycopg2_Binary>=2.9"]\n'''

        self.assertEqual(
            _selector_count("pyproject-dependency", "azure-storage-blob", source),
            1,
        )
        self.assertEqual(
            _selector_count("pyproject-dependency", "psycopg2-binary", source),
            1,
        )

    def test_pyproject_dependency_rejects_malformed_or_ambiguous_input(self) -> None:
        malformed_toml = b'[project]\ndependencies = ["azure-storage-blob"\n'
        malformed_requirement = b'''[project]\ndependencies = ["not a requirement !!!"]\n'''

        for source in (malformed_toml, malformed_requirement):
            with self.subTest(source=source), self.assertRaises(RemovalApprovalError):
                _selector_count("pyproject-dependency", "azure-storage-blob", source)

        duplicate = b'''[project]\ndependencies = ["azure-storage-blob"]\n\n[project.optional-dependencies]\ndev = ["Azure_Storage.Blob"]\n'''
        self.assertEqual(
            _selector_count("pyproject-dependency", "azure-storage-blob", duplicate),
            2,
        )

    def test_requirements_dependency_ignores_comments_options_and_urls(self) -> None:
        source = b'''# azure-storage-blob\n--find-links https://example.invalid/azure-storage-blob\n--index-url https://azure-storage-blob.example.invalid/simple\n--extra-index-url=https://example.invalid/psycopg2-binary\n--require-hashes\n'''

        self.assertEqual(
            _selector_count("requirements-dependency", "azure-storage-blob", source),
            0,
        )
        self.assertEqual(
            _selector_count("requirements-dependency", "psycopg2-binary", source),
            0,
        )

    def test_requirements_dependency_parses_markers_hashes_and_canonical_names(self) -> None:
        source = b'''Azure_Storage.Blob[crypto]>=12; python_version >= "3.11"  # retained\nPsycopg2.Binary==2.9.10 \\\n    --hash=sha256:0123456789abcdef \\\n    --hash=sha256:abcdef0123456789\n'''

        self.assertEqual(
            _selector_count("requirements-dependency", "azure-storage-blob", source),
            1,
        )
        self.assertEqual(
            _selector_count("requirements-dependency", "psycopg2-binary", source),
            1,
        )

    def test_requirements_dependency_rejects_hidden_or_invalid_dependencies(self) -> None:
        sources = (
            b"-r shared-requirements.txt\n",
            b"--constraint constraints.txt\n",
            b"-e git+https://example.invalid/project.git#egg=project\n",
            b"not a requirement !!!\n",
            b"azure-storage-blob \\\n",
        )

        for source in sources:
            with self.subTest(source=source), self.assertRaises(RemovalApprovalError):
                _selector_count("requirements-dependency", "azure-storage-blob", source)

        self.assertEqual(
            _selector_count(
                "requirements-dependency",
                "azure-storage-blob",
                b"azure-storage-blob\nAzure_Storage.Blob\n",
            ),
            2,
        )

    def test_rejects_unlinked_replacement_and_retirement_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            inventory = repository.inventory()
            delete_item = inventory["items"][0]
            delete_item["replacementSuiteIds"] = ["unknown-suite"]
            delete_item["replacementCheckIds"] = ["unknown-check"]
            delete_item["retirementSuiteIds"] = []
            repository.commit_chain(inventory=inventory)

            errors = self._validate(repository)

        self.assertTrue(any("replacementSuiteIds not in test inventory" in e for e in errors))
        self.assertTrue(any("replacementCheckIds not in evidence receipt" in e for e in errors))
        self.assertTrue(any("deleted baseline tests lack retirement mapping" in e for e in errors))
        self.assertTrue(any("semantic retirement suite census drifted" in e for e in errors))

    def test_requires_census_mandated_replacement_suites_per_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            census = json.loads((repository.root / CENSUS_PATH).read_text())
            census["issues"][0]["allowedReplacementSuiteIds"] = [
                "mandatory-absence-scan",
                "target-suite",
            ]
            census["issues"][0]["requiredReplacementSuiteIds"] = [
                "mandatory-absence-scan"
            ]
            self._commit_census(repository, census)
            repository.commit_chain()

            errors = self._validate(repository)

        self.assertTrue(
            any(
                "deletion inventory lacks mandatory replacement suites for "
                "ownerIssue #70" in error
                for error in errors
            ),
            errors,
        )

    def test_rejects_unverifiable_retained_command_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(
                evidence_mutation={
                    "checks": [
                        {
                            "id": "static-target",
                            "command": "npm run web:check",
                            "result": "passed",
                            "outputPath": (
                                "tests/evidence/repository-removal/v1/static-target.json"
                            ),
                            "outputSha256": "0" * 64,
                            "coveredReplacementSuiteIds": ["target-suite"],
                            "coveredTargetOwnerPaths": ["target/runtime.test.ts"],
                            "evidencePaths": [
                                "target/runtime.test.ts",
                                "tests/evidence/repository-removal/v1/static-target.json",
                            ],
                        }
                    ]
                }
            )

            errors = self._validate(repository)

        self.assertIn(
            "static-target: outputSha256 does not match retained command output: "
            "tests/evidence/repository-removal/v1/static-target.json",
            errors,
        )

    def test_rejects_arbitrary_tracked_file_as_check_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(
                check_mutation={
                    "outputPath": "historical/evidence.md",
                    "outputSha256": _sha256(b"historical evidence\n"),
                    "evidencePaths": [
                        "historical/evidence.md",
                        "target/runtime.test.ts",
                    ],
                }
            )

            errors = self._validate(repository)

        self.assertIn(
            "static-target: outputPath must be the canonical check namespace: "
            "tests/evidence/repository-removal/v1/static-target.json",
            errors,
        )

    def test_rejects_structured_check_output_binding_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(
                check_output_mutation={"command": "npm run web:test"}
            )

            errors = self._validate(repository)

        self.assertIn(
            "static-target: committed check output does not exactly bind "
            "auditedCommit/checkId/command/result",
            errors,
        )

    def test_rejects_retirement_suite_owned_by_another_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            inventory = repository.inventory()
            inventory["items"][0]["ownerIssue"] = 71
            repository.commit_chain(inventory=inventory)

            errors = self._validate(repository)

        self.assertIn(
            "delete-runtime: retirementSuiteIds must have replacementGate.issue "
            "equal to ownerIssue: ['legacy-suite']",
            errors,
        )

    def test_rejects_semantically_unbound_check_suite_and_target_path(self) -> None:
        mutations = (
            {"coveredReplacementSuiteIds": ["legacy-suite"]},
            {"coveredTargetOwnerPaths": ["historical/evidence.md"]},
        )
        expected = (
            (
                "delete-runtime: replacement checks do not exactly cover "
                "replacementSuiteIds"
            ),
            "delete-runtime: replacement checks do not exactly cover targetOwnerPaths",
        )
        for mutation, expected_error in zip(mutations, expected):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                repository = ApprovalRepository(Path(directory))
                repository.commit_chain(check_mutation=mutation)

                errors = self._validate(repository)

            self.assertIn(expected_error, errors)

    def test_rejects_consistently_relabelled_unrelated_replacement_suite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            inventory = repository.inventory()
            delete_item = inventory["items"][0]
            delete_item["replacementSuiteIds"] = ["other-issue-suite"]
            delete_item["replacementEvidence"][0]["reference"] = "other-issue-suite"
            repository.commit_chain(
                inventory=inventory,
                check_mutation={
                    "coveredReplacementSuiteIds": ["other-issue-suite"]
                },
            )

            errors = self._validate(repository)

        self.assertIn(
            "delete-runtime: replacementSuiteIds are not allowed for ownerIssue "
            "#70: ['other-issue-suite']",
            errors,
        )

    def test_rejects_consistently_bound_true_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain(
                check_mutation={"command": "true"},
                check_output_mutation={"command": "true"},
            )

            errors = self._validate(repository)

        self.assertIn(
            "static-target: command must exactly match target-suite "
            "commands.focused or commands.full",
            errors,
        )

    def test_rejects_consistently_bound_unrelated_workflow_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            inventory = repository.inventory()
            inventory["items"][0]["targetOwnerPaths"] = [
                ".github/workflows/ci.yml"
            ]
            output_path = "tests/evidence/repository-removal/v1/static-target.json"
            repository.commit_chain(
                inventory=inventory,
                check_mutation={
                    "coveredTargetOwnerPaths": [".github/workflows/ci.yml"],
                    "evidencePaths": [".github/workflows/ci.yml", output_path],
                },
            )

            errors = self._validate(repository)

        self.assertIn(
            "static-target: covered suite target-suite has no matching "
            "coveredTargetOwnerPath",
            errors,
        )
        self.assertIn(
            "static-target: coveredTargetOwnerPaths do not match covered suite "
            "sourcePaths: ['.github/workflows/ci.yml']",
            errors,
        )

    def test_requires_live_owner_comment_and_rejects_live_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ApprovalRepository(Path(directory))
            repository.commit_chain()

            offline_errors = self._validate(repository, verify_owner_comment=False)
            live_errors = self._validate(
                repository,
                live_comment_mutation={"author_association": "CONTRIBUTOR"},
            )

        self.assertIn(
            "live GitHub owner comment verification is required for approval",
            offline_errors,
        )
        self.assertIn(
            "live GitHub owner comment does not exactly match the recorded owner approval",
            live_errors,
        )


if __name__ == "__main__":
    unittest.main()
