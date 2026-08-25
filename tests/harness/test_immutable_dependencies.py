from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.ci.changed_components import classify_paths
from scripts.ci.validate_immutable_dependencies import validate_repository


class ImmutableDependencyTests(unittest.TestCase):
    def test_checked_in_build_and_release_dependencies_are_immutable(self) -> None:
        root = Path(__file__).resolve().parents[2]

        self.assertEqual(validate_repository(root), [])

    def test_ci_runs_dependency_validation_before_component_routing(self) -> None:
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        changes_job = workflow.split("  changes:\n", maxsplit=1)[1].split(
            "\n  docs:", maxsplit=1
        )[0]

        self.assertNotIn("\n    if:", changes_job)
        self.assertIn("Validate immutable third-party dependencies", changes_job)
        self.assertIn(
            "python3 scripts/ci/validate_immutable_dependencies.py", changes_job
        )
        self.assertLess(
            changes_job.index("Validate immutable third-party dependencies"),
            changes_job.index("id: route"),
        )
        for path in (".github/workflows/codeql.yml",):
            with self.subTest(path=path):
                self.assertTrue(any(classify_paths([path]).values()))

    def test_rejects_mutable_action_and_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "release.yml").write_text(
                "steps:\n  - uses: actions/checkout@v4\n"
                "container: python:3.11\n",
                encoding="utf-8",
            )
            (root / "Dockerfile").write_text(
                "FROM node:20-alpine AS base\nFROM base AS runtime\n",
                encoding="utf-8",
            )
            (root / "docker-compose.yml").write_text(
                "services:\n  database:\n    image: postgis/postgis:16-3.4\n",
                encoding="utf-8",
            )

            errors = validate_repository(root)

        self.assertEqual(len(errors), 4)
        self.assertTrue(any("Action must use a full commit SHA" in error for error in errors))
        self.assertEqual(
            sum("container image must use a sha256 digest" in error for error in errors),
            2,
        )
        self.assertTrue(any("Docker base image must use a sha256 digest" in error for error in errors))

    def test_accepts_pinned_actions_images_and_named_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "release.yml").write_text(
                "steps:\n  - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567\n",
                encoding="utf-8",
            )
            (root / "Dockerfile").write_text(
                "FROM node:20-alpine@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef AS base\n"
                "FROM base AS runtime\n",
                encoding="utf-8",
            )

            self.assertEqual(validate_repository(root), [])


if __name__ == "__main__":
    unittest.main()
