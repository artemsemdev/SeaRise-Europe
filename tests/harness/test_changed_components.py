from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.ci.changed_components import (
    OUTPUTS,
    classify_paths,
    parse_name_status,
    release_only_outputs,
    write_github_outputs,
)


class ChangedComponentRoutingTests(unittest.TestCase):
    def test_markdown_only_change_skips_heavy_jobs(self) -> None:
        outputs = classify_paths(["README.md", "docs/architecture/README.md"])

        self.assertFalse(outputs["heavy"])
        self.assertTrue(all(not outputs[name] for name in OUTPUTS))

    def test_frontend_runtime_change_routes_tests_image_and_codeql(self) -> None:
        outputs = classify_paths(["src/frontend/src/app/page.tsx"])

        self.assertTrue(outputs["frontend"])
        self.assertTrue(outputs["docker_frontend"])
        self.assertTrue(outputs["codeql_javascript"])
        self.assertFalse(outputs["api"])
        self.assertFalse(outputs["pipeline"])
        self.assertFalse(outputs["compose"])

    def test_frontend_test_change_does_not_rebuild_image(self) -> None:
        outputs = classify_paths(
            ["src/frontend/src/__tests__/components/ResultPanel.test.tsx"]
        )

        self.assertTrue(outputs["frontend"])
        self.assertFalse(outputs["docker_frontend"])

    def test_pipeline_change_does_not_route_runtime_stack(self) -> None:
        outputs = classify_paths(["src/pipeline/searise_pipeline/science/ar6.py"])

        self.assertTrue(outputs["pipeline"])
        self.assertTrue(outputs["release"])
        self.assertFalse(outputs["frontend"])
        self.assertFalse(outputs["api"])
        self.assertFalse(outputs["infrastructure"])
        self.assertFalse(outputs["compose"])

    def test_ordinary_pipeline_change_skips_release_toolchain(self) -> None:
        outputs = classify_paths(["src/pipeline/searise_pipeline/config.py"])

        self.assertTrue(outputs["pipeline"])
        self.assertFalse(outputs["release"])

    def test_release_contract_routes_release_toolchain(self) -> None:
        outputs = classify_paths(["src/pipeline/science/ar6-regional-release.json"])

        self.assertTrue(outputs["pipeline"])
        self.assertTrue(outputs["release"])

    def test_release_source_evidence_routes_release_toolchain(self) -> None:
        paths = [
            "src/pipeline/science/evidence/ar6-lookup-goldens.json",
            "src/pipeline/science/source-semantics.json",
            "src/pipeline/sources/source-lock.json",
        ]

        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(classify_paths([path])["release"])

    def test_infrastructure_schema_change_routes_api_and_compose(self) -> None:
        outputs = classify_paths(["infra/db/init.sql"])

        self.assertTrue(outputs["infrastructure"])
        self.assertTrue(outputs["api"])
        self.assertTrue(outputs["compose"])
        self.assertFalse(outputs["frontend"])

    def test_shared_contract_routes_all_language_tests_without_images(self) -> None:
        outputs = classify_paths(
            ["tests/fixtures/tdd/five-state-characterization-v1.json"]
        )

        self.assertTrue(outputs["frontend"])
        self.assertTrue(outputs["api"])
        self.assertTrue(outputs["pipeline"])
        self.assertFalse(outputs["docker_frontend"])
        self.assertFalse(outputs["docker_api"])

    def test_ci_router_change_exercises_every_route(self) -> None:
        outputs = classify_paths(["scripts/ci/changed_components.py"])

        self.assertTrue(all(outputs[name] for name in OUTPUTS))

    def test_release_evidence_dispatch_skips_unrelated_jobs(self) -> None:
        outputs = release_only_outputs()

        self.assertTrue(outputs["release"])
        self.assertTrue(outputs["heavy"])
        self.assertTrue(
            all(
                not outputs[name]
                for name in OUTPUTS
                if name not in {"release", "heavy"}
            )
        )

    def test_release_evidence_dispatch_skips_fixture_toolchain_job(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "github.event_name != 'workflow_dispatch'",
            workflow,
        )

    def test_gitignore_change_only_routes_pipeline_contracts(self) -> None:
        outputs = classify_paths([".gitignore"])

        self.assertTrue(outputs["pipeline"])
        self.assertTrue(outputs["heavy"])
        self.assertFalse(outputs["frontend"])
        self.assertFalse(outputs["api"])

    def test_rename_routes_both_old_and_new_paths(self) -> None:
        paths = parse_name_status(
            "R100\tsrc/api/Old.cs\tdocs/old-api.md\nM\tREADME.md\n"
        )

        self.assertEqual(paths, ["src/api/Old.cs", "docs/old-api.md", "README.md"])
        self.assertTrue(classify_paths(paths)["api"])

    def test_github_outputs_are_lowercase_and_stable(self) -> None:
        outputs = classify_paths(["src/pipeline/config.py"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "github-output"
            write_github_outputs(path, outputs)
            lines = path.read_text(encoding="utf-8").splitlines()

        self.assertEqual([line.split("=", 1)[0] for line in lines], list(OUTPUTS))
        self.assertIn("pipeline=true", lines)
        self.assertIn("frontend=false", lines)


if __name__ == "__main__":
    unittest.main()
