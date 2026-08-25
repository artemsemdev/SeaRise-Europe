from __future__ import annotations

import unittest

from scripts.ci.verify_ci_gate import GateVerificationError, verify_gate_results

ROUTES = {
    "docs": False,
    "web": False,
    "pipeline": False,
    "release": False,
    "repository_removal": False,
}
JOBS = {
    "changes": "success",
    "docs": "skipped",
    "web": "skipped",
    "pipeline": "skipped",
    "settlement-spatial-toolchain-macos": "skipped",
    "offline-release-fixture": "skipped",
    "release-toolchain": "skipped",
    "release-toolchain-macos": "skipped",
    "ar6-release-evidence": "skipped",
    "ar6-release-evidence-macos": "skipped",
    "repository-removal-v2": "skipped",
}


def changed(source: dict[str, object], **updates: object) -> dict[str, object]:
    return {**source, **updates}


class CiGateVerificationTests(unittest.TestCase):
    def test_selected_target_job_must_succeed(self) -> None:
        with self.assertRaisesRegex(GateVerificationError, "web.*skipped"):
            verify_gate_results("ci", changed(ROUTES, web=True), JOBS)

    def test_unselected_job_must_be_skipped(self) -> None:
        with self.assertRaisesRegex(GateVerificationError, "web.*success"):
            verify_gate_results(
                "ci",
                changed(ROUTES, docs=True),
                changed(JOBS, docs="success", web="success"),
            )

    def test_manual_release_requires_both_exact_evidence_jobs(self) -> None:
        routes = changed(ROUTES, release=True)
        jobs = changed(
            JOBS,
            **{
                "ar6-release-evidence": "success",
                "ar6-release-evidence-macos": "success",
            },
        )

        verify_gate_results("ci", routes, jobs, release_evidence=True)

        with self.assertRaisesRegex(
            GateVerificationError, "ar6-release-evidence-macos.*skipped"
        ):
            verify_gate_results(
                "ci",
                routes,
                changed(jobs, **{"ar6-release-evidence-macos": "skipped"}),
                release_evidence=True,
            )

    def test_codeql_selected_language_must_succeed(self) -> None:
        routes = {"codeql_javascript": True}
        jobs = {"changes": "success", "analyze-javascript": "skipped"}

        with self.assertRaisesRegex(
            GateVerificationError, "analyze-javascript.*skipped"
        ):
            verify_gate_results("codeql", routes, jobs)


if __name__ == "__main__":
    unittest.main()
