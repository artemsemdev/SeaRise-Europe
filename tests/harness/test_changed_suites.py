from __future__ import annotations

import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.tests.changed_suites import (
    _run_commands,
    fast_local_suites,
    path_matches,
    select_suites,
)
from scripts.tests.validate_test_inventory import (
    _discover_test_files,
    load_inventory,
    validate_inventory,
)


class ChangedSuiteRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = load_inventory()

    def test_inventory_is_valid_before_it_drives_routing(self) -> None:
        self.assertEqual(validate_inventory(self.inventory), [])

    def test_shared_fixture_routes_all_three_language_controls(self) -> None:
        suites = select_suites(
            self.inventory,
            ["tests/fixtures/tdd/five-state-characterization-v1.json"],
        )
        suite_ids = {suite["id"] for suite in suites}

        self.assertTrue(
            {
                "api-shared-characterization",
                "frontend-five-state-characterization",
                "pipeline-five-state-characterization",
            }.issubset(suite_ids)
        )

    def test_fast_filter_excludes_docker_and_credentials(self) -> None:
        suites = select_suites(
            self.inventory,
            ["src/frontend/src/lib/domain/resultState.ts"],
        )
        fast_suites = fast_local_suites(suites)

        self.assertTrue(fast_suites)
        self.assertTrue(
            all(not suite["execution"]["requiresDocker"] for suite in fast_suites)
        )
        self.assertNotIn(
            "container-frontend-build", {suite["id"] for suite in fast_suites}
        )

    def test_globs_normalize_windows_separators(self) -> None:
        self.assertTrue(
            path_matches("src\\frontend\\src\\app\\page.tsx", "src/frontend/**")
        )

    def test_selection_order_is_deterministic(self) -> None:
        suites = select_suites(
            self.inventory, ["src/frontend/src/lib/store/appStore.ts"]
        )
        ids = [suite["id"] for suite in suites]

        self.assertEqual(ids, sorted(ids))

    def test_build_plane_validator_routes_supply_chain_contract(self) -> None:
        suites = select_suites(
            self.inventory,
            ["scripts/release/validate_build_plane_sbom.py"],
        )

        self.assertIn(
            "pipeline-supply-chain-contract", {suite["id"] for suite in suites}
        )

    def test_legacy_infrastructure_routes_deletion_owners(self) -> None:
        database_suites = select_suites(self.inventory, ["infra/db/init.sql"])
        blob_seed_suites = select_suites(self.inventory, ["infra/blob-seed/seed.py"])

        self.assertIn(
            "api-postgis-integration", {suite["id"] for suite in database_suites}
        )
        self.assertIn("compose-smoke", {suite["id"] for suite in blob_seed_suites})

    def test_every_current_suite_has_explicit_active_lifecycle(self) -> None:
        self.assertTrue(self.inventory["suites"])
        for suite in self.inventory["suites"]:
            self.assertEqual(suite["status"], "active")
            self.assertIsNone(suite["removalGate"])
            self.assertIsNone(suite["replacementEvidence"])

    def test_retired_suite_can_reference_removed_sources_with_evidence(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        suite = inventory["suites"][0]
        suite.update(
            status="retired",
            removalGate=73,
            replacementEvidence="PR #999 target contract evidence",
            sourcePaths=["removed/legacy-suite/*.test.ts"],
        )
        for item in inventory["baselineTests"]:
            if item["suite"] == suite["id"]:
                item.update(
                    status="retired",
                    removalGate=73,
                    replacementEvidence="PR #999 target contract evidence",
                )

        errors = validate_inventory(inventory)

        self.assertFalse(any("matches no files" in error for error in errors), errors)

    def test_retired_suite_requires_gate_and_replacement_evidence(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        suite = inventory["suites"][0]
        suite.update(status="retired", removalGate=None, replacementEvidence=None)

        errors = validate_inventory(inventory)

        self.assertTrue(
            any("retired suite requires gate and evidence" in error for error in errors),
            errors,
        )

    def test_active_suite_rejects_retirement_metadata(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        inventory["suites"][0].update(
            removalGate=73,
            replacementEvidence="not valid while active",
        )

        errors = validate_inventory(inventory)

        self.assertTrue(
            any("active suite cannot carry retirement metadata" in error for error in errors),
            errors,
        )

    def test_active_baseline_cannot_be_owned_by_retired_suite(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        suite_id = inventory["baselineTests"][0]["suite"]
        suite = next(item for item in inventory["suites"] if item["id"] == suite_id)
        suite.update(
            status="retired",
            removalGate=73,
            replacementEvidence="PR #999 target contract evidence",
        )

        errors = validate_inventory(inventory)

        self.assertTrue(
            any("active baseline is owned by retired suite" in error for error in errors),
            errors,
        )

    def test_existing_test_cannot_be_declared_retired(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        baseline = inventory["baselineTests"][0]
        baseline.update(
            status="retired",
            removalGate=73,
            replacementEvidence="PR #999 target contract evidence",
        )

        errors = validate_inventory(inventory)

        self.assertTrue(
            any("on-disk test cannot be declared retired" in error for error in errors),
            errors,
        )

    def test_retired_baseline_requires_gate_and_evidence(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        inventory["baselineTests"][0].update(
            status="retired", removalGate=None, replacementEvidence=None
        )

        errors = validate_inventory(inventory)

        self.assertTrue(
            any("retired test requires gate and evidence" in error for error in errors),
            errors,
        )

    def test_retired_suite_is_excluded_at_every_routing_boundary(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        suite = inventory["suites"][0]
        suite.update(
            status="retired",
            removalGate=73,
            replacementEvidence="PR #999 target contract evidence",
            changedPaths=["retired/**"],
        )

        self.assertEqual(select_suites(inventory, ["retired/test.ts"]), [])
        self.assertEqual(fast_local_suites([suite]), [])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertNotEqual(_run_commands([suite]), 0)
        self.assertNotIn("RUN ", output.getvalue())
        self.assertIn("refusing to run non-active", output.getvalue())

    def test_runner_fails_closed_on_malformed_suite_status(self) -> None:
        for malformed_status in (None, "activ"):
            with self.subTest(status=malformed_status):
                suite = copy.deepcopy(self.inventory["suites"][0])
                if malformed_status is None:
                    del suite["status"]
                else:
                    suite["status"] = malformed_status
                output = io.StringIO()

                with redirect_stdout(output):
                    self.assertNotEqual(_run_commands([suite]), 0)

                self.assertNotIn("RUN ", output.getvalue())
                self.assertIn("refusing to run non-active", output.getvalue())

    def test_compose_smoke_is_discovered_only_while_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "src/pipeline/tests",
                "src/frontend/src",
                "src/frontend/scripts",
                "src/web/src",
                "src/web/scripts",
                "src/web/tests",
                "tests/harness",
                "src/api/SeaRise.Api.Tests",
                "scripts",
            ):
                (root / relative).mkdir(parents=True, exist_ok=True)

            with patch("scripts.tests.validate_test_inventory.ROOT", root):
                self.assertNotIn("scripts/compose-smoke.sh", _discover_test_files())
                (root / "scripts/compose-smoke.sh").write_text("#!/bin/sh\n")
                self.assertIn("scripts/compose-smoke.sh", _discover_test_files())

    def test_frontend_python_test_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "src/pipeline/tests",
                "src/frontend/src",
                "src/frontend/scripts",
                "src/web/src",
                "src/web/scripts",
                "src/web/tests",
                "tests/harness",
                "src/api/SeaRise.Api.Tests",
                "scripts",
            ):
                (root / relative).mkdir(parents=True, exist_ok=True)

            test_path = root / "src/frontend/scripts/test-browser-shard-fs.py"
            test_path.write_text("def test_fixture(): pass\n")
            with patch("scripts.tests.validate_test_inventory.ROOT", root):
                self.assertIn(
                    "src/frontend/scripts/test-browser-shard-fs.py",
                    _discover_test_files(),
                )


if __name__ == "__main__":
    unittest.main()
