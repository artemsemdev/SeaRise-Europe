from __future__ import annotations

import unittest

from scripts.tests.changed_suites import fast_local_suites, path_matches, select_suites
from scripts.tests.validate_test_inventory import load_inventory, validate_inventory


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
        self.assertTrue(all(not suite["execution"]["requiresDocker"] for suite in fast_suites))
        self.assertNotIn("container-frontend-build", {suite["id"] for suite in fast_suites})

    def test_globs_normalize_windows_separators(self) -> None:
        self.assertTrue(path_matches("src\\frontend\\src\\app\\page.tsx", "src/frontend/**"))

    def test_selection_order_is_deterministic(self) -> None:
        suites = select_suites(self.inventory, ["src/frontend/src/lib/store/appStore.ts"])
        ids = [suite["id"] for suite in suites]

        self.assertEqual(ids, sorted(ids))


if __name__ == "__main__":
    unittest.main()
