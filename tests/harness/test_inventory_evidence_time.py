"""Regression tests for test-inventory evidence timestamps."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

from scripts.tests.validate_test_inventory import load_inventory, validate_inventory


class InventoryEvidenceTimeTests(unittest.TestCase):
    def test_future_evidence_is_rejected(self) -> None:
        inventory = copy.deepcopy(load_inventory())
        now = datetime(2026, 8, 16, 5, 0, tzinfo=timezone.utc)
        inventory["evidence"]["local-2026-08-16-private-candidate-binding"][
            "observedAt"
        ] = (now + timedelta(hours=1)).isoformat()

        errors = validate_inventory(inventory, now=now)

        self.assertIn(
            "local-2026-08-16-private-candidate-binding: observedAt is in the future",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
