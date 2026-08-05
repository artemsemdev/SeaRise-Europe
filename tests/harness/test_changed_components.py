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


def _workflow_job(workflow: str, job: str, next_job: str) -> str:
    return workflow.split(f"  {job}:", maxsplit=1)[1].split(
        f"\n  {next_job}:", maxsplit=1
    )[0]


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

    def test_release_evidence_requires_selector_and_exact_revision(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")

        dispatch = workflow.split("permissions:", maxsplit=1)[0]
        changes = workflow.split("  changes:", maxsplit=1)[1].split(
            "\n  frontend:", maxsplit=1
        )[0]
        evidence = _workflow_job(
            workflow,
            "ar6-release-evidence",
            "ar6-release-evidence-macos",
        )
        macos_evidence = _workflow_job(
            workflow,
            "ar6-release-evidence-macos",
            "infrastructure",
        )
        self.assertIn("release_evidence:\n", dispatch)
        self.assertIn("default: false", dispatch)
        self.assertIn("release_source_revision:\n", dispatch)
        self.assertIn("--release-only", changes)
        self.assertIn("^[0-9a-f]{40}$", changes)
        self.assertIn('"${RELEASE_SOURCE_REVISION}" != "${GITHUB_SHA}"', changes)
        self.assertIn('"${GITHUB_RUN_ATTEMPT}" != "1"', changes)
        self.assertLess(
            changes.index("Validate manual workflow request"),
            changes.index("uses: actions/checkout"),
        )
        self.assertIn("inputs.release_evidence == true", evidence)
        self.assertIn("needs: changes", evidence)
        self.assertIn("^[0-9a-f]{40}$", evidence)
        self.assertIn('"${RELEASE_SOURCE_REVISION}" != "${GITHUB_SHA}"', evidence)
        self.assertIn('"${GITHUB_RUN_ATTEMPT}" != "1"', evidence)
        self.assertLess(
            evidence.index("Validate exact release source revision"),
            evidence.index("uses: actions/checkout"),
        )
        self.assertIn("inputs.release_evidence == true", macos_evidence)
        self.assertIn("needs: changes", macos_evidence)
        self.assertIn("^[0-9a-f]{40}$", macos_evidence)
        self.assertIn(
            '"${RELEASE_SOURCE_REVISION}" != "${GITHUB_SHA}"',
            macos_evidence,
        )
        self.assertIn('"${GITHUB_RUN_ATTEMPT}" != "1"', macos_evidence)
        self.assertLess(
            macos_evidence.index("Validate exact release source revision"),
            macos_evidence.index("uses: actions/checkout"),
        )
        self.assertNotIn("inputs.release_source_revision || github.sha", workflow)

    def test_release_evidence_pins_actions_and_checks_disk_before_download(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        evidence = _workflow_job(
            workflow,
            "ar6-release-evidence",
            "ar6-release-evidence-macos",
        )
        macos_evidence = _workflow_job(
            workflow,
            "ar6-release-evidence-macos",
            "infrastructure",
        )

        for action in (
            "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            "actions/cache@0400d5f644dc74513175e3cd8d07132dd4860809",
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        ):
            self.assertIn(action, evidence)
        self.assertIn("required_kib=10599985", evidence)
        self.assertIn("/tmp/phase-0r-ar6-preflight", evidence)
        self.assertLess(evidence.index("df -Pk /tmp"), evidence.index("zenodo.org"))
        self.assertIn("overwrite: false", evidence)
        for action in (
            "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            "actions/cache@0400d5f644dc74513175e3cd8d07132dd4860809",
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        ):
            self.assertIn(action, macos_evidence)
        self.assertIn("required_kib=10599985", macos_evidence)
        self.assertLess(
            macos_evidence.index("df -Pk /tmp"),
            macos_evidence.index("zenodo.org"),
        )
        self.assertIn("overwrite: false", macos_evidence)

    def test_release_evidence_builds_two_exact_trusted_profiles(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        linux = _workflow_job(
            workflow,
            "ar6-release-evidence",
            "ar6-release-evidence-macos",
        )
        macos = _workflow_job(
            workflow,
            "ar6-release-evidence-macos",
            "infrastructure",
        )

        self.assertIn("name: Full-source Linux AR6 candidate", linux)
        self.assertIn("runs-on: ubuntu-24.04", linux)
        self.assertIn('python-version: "3.11.9"', linux)
        self.assertIn("requirements-release.lock", linux)
        self.assertIn(
            'build-environment-id "github-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-linux-x86_64"',
            linux,
        )
        self.assertIn(
            "name: ar6-linux-candidate-${{ inputs.release_source_revision }}-${{ github.run_id }}",
            linux,
        )
        self.assertIn("/tmp/build-timing-linux.json", linux)

        self.assertIn("name: Full-source macOS ARM64 AR6 candidate", macos)
        self.assertIn("runs-on: macos-14", macos)
        self.assertIn('test "$(uname -m)" = "arm64"', macos)
        self.assertIn('python-version: "3.9.6"', macos)
        self.assertIn("requirements-release-macos-arm64.lock", macos)
        self.assertIn("tippecanoe-darwin-arm64-build-receipt.json", macos)
        self.assertIn("--pmtiles-distribution-platform darwin-arm64", macos)
        self.assertIn(
            'build-environment-id "github-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-macos-arm64"',
            macos,
        )
        self.assertIn(
            "name: ar6-macos-arm64-candidate-${{ inputs.release_source_revision }}-${{ github.run_id }}",
            macos,
        )
        self.assertIn("/tmp/build-timing-macos-arm64.json", macos)
        self.assertEqual(linux.count("/tmp/phase-0r-ar6-v1"), 4)
        self.assertEqual(macos.count("/tmp/phase-0r-ar6-v1"), 4)

    def test_release_evidence_uses_only_hashed_python_install(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        evidence = _workflow_job(
            workflow,
            "ar6-release-evidence",
            "ar6-release-evidence-macos",
        )
        macos_evidence = _workflow_job(
            workflow,
            "ar6-release-evidence-macos",
            "infrastructure",
        )

        self.assertIn("--require-hashes -r requirements-release.lock", evidence)
        self.assertEqual(evidence.count("pip install"), 1)
        self.assertNotIn("pip install -e", evidence)
        self.assertIn(
            "--require-hashes -r requirements-release-macos-arm64.lock",
            macos_evidence,
        )
        self.assertEqual(macos_evidence.count("pip install"), 1)
        self.assertNotIn("pip install -e", macos_evidence)

    def test_release_evidence_preflights_before_source_download(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        evidence = _workflow_job(
            workflow,
            "ar6-release-evidence",
            "ar6-release-evidence-macos",
        )
        macos_evidence = _workflow_job(
            workflow,
            "ar6-release-evidence-macos",
            "infrastructure",
        )

        preflight = evidence.index("Preflight exact release environment and fixture")
        acquire = evidence.index("Acquire and verify locked AR6 archive")
        self.assertLess(preflight, acquire)
        self.assertIn("--fixture src/pipeline/fixtures/ar6-regional-release", evidence)
        self.assertNotIn("ar6-archive-cache", evidence)
        macos_preflight = macos_evidence.index(
            "Preflight exact release environment and fixture"
        )
        macos_acquire = macos_evidence.index("Acquire and verify locked AR6 archive")
        self.assertLess(macos_preflight, macos_acquire)
        self.assertIn(
            "--fixture src/pipeline/fixtures/ar6-regional-release",
            macos_evidence,
        )
        self.assertNotIn("ar6-archive-cache", macos_evidence)

    def test_release_evidence_is_in_ci_gate_only_as_a_routed_job(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")

        toolchain = workflow.split("  release-toolchain:", maxsplit=1)[1].split(
            "\n  ar6-release-evidence:", maxsplit=1
        )[0]
        gate = workflow.split("  ci-gate:", maxsplit=1)[1]
        self.assertIn("needs.changes.outputs.release == 'true'", toolchain)
        self.assertIn("inputs.release_evidence != true", toolchain)
        self.assertIn("      - ar6-release-evidence", gate)
        self.assertIn("      - ar6-release-evidence-macos", gate)

    def test_release_environment_preflight_is_isolated_from_general_tests(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")

        start = workflow.index("  release-toolchain:")
        end = workflow.index("  ar6-release-evidence:", start)
        preflight = workflow[start:end]
        self.assertIn("--require-hashes -r requirements-release.lock", preflight)
        self.assertIn("tests/release/test_toolchain.py", preflight)
        self.assertNotIn("ar6-regional-confidence.zip/content", preflight)
        gate = workflow[workflow.index("  ci-gate:") :]
        self.assertIn("      - release-toolchain", gate)

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
