from __future__ import annotations

import json
import re
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


def _workflow_event_paths(workflow: str, event: str, next_event: str) -> set[str]:
    event_block = workflow.split(f"  {event}:\n", maxsplit=1)[1].split(
        f"  {next_event}:\n", maxsplit=1
    )[0]
    paths_block = event_block.split("    paths:\n", maxsplit=1)[1]
    return {
        match.group(1)
        for match in re.finditer(r'^      - "([^"]+)"$', paths_block, re.MULTILINE)
    }


class ChangedComponentRoutingTests(unittest.TestCase):
    def test_static_quality_routes_every_direct_release_fixture_input(self) -> None:
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github/workflows/static-quality.yml").read_text(
            encoding="utf-8"
        )
        expected = {
            "contracts/release/v1/fixtures/release/**",
            "contracts/release/v2/fixtures/browser-release/**",
        }

        self.assertLessEqual(
            expected,
            _workflow_event_paths(workflow, "pull_request", "push"),
        )
        self.assertLessEqual(
            expected,
            _workflow_event_paths(workflow, "push", "workflow_dispatch"),
        )

    def test_release_evidence_exports_exact_producer_contract(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = json.loads(
            (root / "tests/contracts/ar6-release-evidence-producers.json").read_text(
                encoding="utf-8"
            )
        )
        workflow = (root / contract["workflow"]).read_text(encoding="utf-8")

        self.assertEqual(contract["schemaVersion"], 1)
        self.assertEqual(
            [producer["jobId"] for producer in contract["producers"]],
            ["ar6-release-evidence", "ar6-release-evidence-macos"],
        )
        for producer in contract["producers"]:
            job = _workflow_job(
                workflow,
                producer["jobId"],
                producer["nextJobId"],
            )
            artifact_name = producer["artifactNameTemplate"].replace(
                "{sourceRevision}", "${{ inputs.release_source_revision }}"
            ).replace("{runId}", "${{ github.run_id }}")

            self.assertIn(f"name: {producer['jobName']}", job)
            self.assertIn(f"name: {artifact_name}", job)

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

    def test_static_web_change_routes_only_target_web_and_codeql(self) -> None:
        outputs = classify_paths(["src/web/src/App.tsx"])

        self.assertTrue(outputs["web"])
        self.assertTrue(outputs["codeql_javascript"])
        self.assertFalse(outputs["frontend"])
        self.assertFalse(outputs["docker_frontend"])
        self.assertFalse(outputs["api"])
        self.assertFalse(outputs["compose"])

    def test_static_quality_tool_change_routes_web_and_javascript_codeql(self) -> None:
        for path in (
            "tools/static-quality/package-lock.json",
            "tools/static-quality/run-lighthouse-gate.mjs",
        ):
            with self.subTest(path=path):
                outputs = classify_paths([path])
                self.assertTrue(outputs["web"])
                self.assertTrue(outputs["codeql_javascript"])
                self.assertFalse(outputs["frontend"])
                self.assertFalse(outputs["api"])

    def test_static_repository_gate_authorities_route_web_validation(self) -> None:
        paths = (
            ".github/workflows/static-quality.yml",
            ".github/workflows/offline-release-controlled.yml",
            "contracts/repository-removal/v1/historical-allowlist.preapproval.json",
            "contracts/supply-chain/v2/static-target-profile.json",
            "contracts/supply-chain/v2/static-target-profile.schema.json",
            "docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md",
            "docs/methodology.md",
            "docs/product/Mock/SeaRise-Flight.html",
            "docs/product/Mock/MOCK_REQUIREMENTS_MAP.md",
        )

        for path in paths:
            with self.subTest(path=path):
                outputs = classify_paths([path])
                self.assertTrue(outputs["web"])
                self.assertTrue(outputs["heavy"])

    def test_frontend_test_change_does_not_rebuild_image(self) -> None:
        outputs = classify_paths(
            ["src/frontend/src/__tests__/components/ResultPanel.test.tsx"]
        )

        self.assertTrue(outputs["frontend"])
        self.assertFalse(outputs["docker_frontend"])

    def test_pmtiles_render_authorities_route_static_web_evidence_check(self) -> None:
        paths = [
            "src/pipeline/evidence/phase-1/pmtiles-render-v1/receipt.json",
            "src/pipeline/evidence/phase-1/pmtiles-render-v1/z3-4-2-median_mm.png",
            "src/pipeline/evidence/ar6-regional-release/owner-promotion/final-gate.json",
            "src/pipeline/fixtures/ar6-regional-release/source-fixture.json.gz",
        ]

        for path in paths:
            with self.subTest(path=path):
                outputs = classify_paths([path])
                self.assertTrue(outputs["web"])
                self.assertTrue(outputs["pipeline"])
                self.assertFalse(outputs["frontend"])
                self.assertFalse(outputs["docker_frontend"])

    def test_static_pmtiles_release_dependencies_route_macos_toolchain(self) -> None:
        paths = [
            "package.json",
            "package-lock.json",
            "src/web/package.json",
            "src/web/scripts/verify-boundary-pmtiles-browser.mjs",
        ]

        for path in paths:
            with self.subTest(path=path):
                outputs = classify_paths([path])
                self.assertTrue(outputs["web"])
                self.assertTrue(outputs["release"])
                self.assertFalse(outputs["frontend"])
                self.assertFalse(outputs["docker_frontend"])
                self.assertFalse(outputs["api"])
                self.assertFalse(outputs["compose"])

    def test_unrelated_static_and_pipeline_paths_skip_release_toolchain(self) -> None:
        paths = [
            "src/web/src/App.tsx",
            "src/web/scripts/render-pmtiles-evidence.mjs",
            "src/pipeline/evidence/phase-1/other-evidence/receipt.json",
            "src/pipeline/evidence/unrelated/receipt.json",
        ]

        for path in paths:
            with self.subTest(path=path):
                outputs = classify_paths([path])
                self.assertFalse(outputs["release"])

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

    def test_supply_chain_validator_routes_pipeline_contracts(self) -> None:
        outputs = classify_paths(["scripts/release/validate_supply_chain_contract.py"])

        self.assertTrue(outputs["pipeline"])
        self.assertFalse(outputs["release"])

    def test_settlement_artifact_routes_pipeline_contracts(self) -> None:
        outputs = classify_paths(
            ["data/settlements/europe-settlement-shoreline-v1.geojson"]
        )

        self.assertTrue(outputs["pipeline"])
        self.assertTrue(outputs["heavy"])
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

    def test_public_release_contract_routes_python_and_frontend_only(self) -> None:
        outputs = classify_paths(["contracts/release/v1/manifest.schema.json"])

        self.assertTrue(outputs["frontend"])
        self.assertTrue(outputs["web"])
        self.assertTrue(outputs["pipeline"])
        self.assertFalse(outputs["api"])
        self.assertFalse(outputs["release"])
        self.assertFalse(outputs["docker_frontend"])
        self.assertFalse(outputs["docker_api"])
        self.assertFalse(outputs["compose"])
        candidate = classify_paths(
            ["contracts/candidate-completeness/v1/candidate.schema.json"]
        )
        self.assertTrue(candidate["frontend"])
        self.assertTrue(candidate["pipeline"])

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
            "\n  web:", maxsplit=1
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
        self.assertIn('"${GITHUB_REF_NAME}" != "master"', changes)
        self.assertIn("^[0-9a-f]{40}$", changes)
        self.assertIn('"${RELEASE_SOURCE_REVISION}" != "${GITHUB_SHA}"', changes)
        self.assertIn('"${GITHUB_RUN_ATTEMPT}" != "1"', changes)
        self.assertLess(
            changes.index("Validate manual workflow request"),
            changes.index("uses: actions/checkout"),
        )

        self.assertIn("inputs.release_evidence == true", evidence)
        self.assertIn("github.ref_name == 'master'", evidence)
        self.assertIn("needs: changes", evidence)
        self.assertIn('"${GITHUB_REF_NAME}" != "master"', evidence)
        self.assertIn("^[0-9a-f]{40}$", evidence)
        self.assertIn('"${RELEASE_SOURCE_REVISION}" != "${GITHUB_SHA}"', evidence)
        self.assertIn('"${GITHUB_RUN_ATTEMPT}" != "1"', evidence)
        self.assertLess(
            evidence.index("Validate exact release source revision"),
            evidence.index("uses: actions/checkout"),
        )
        self.assertIn("inputs.release_evidence == true", macos_evidence)
        self.assertIn("github.ref_name == 'master'", macos_evidence)
        self.assertIn("needs: changes", macos_evidence)
        self.assertIn('"${GITHUB_REF_NAME}" != "master"', macos_evidence)
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

    def test_static_web_can_verify_the_owner_approval_chain(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        web = _workflow_job(workflow, "web", "frontend")

        self.assertIn("permissions:\n      contents: read\n      issues: read", web)
        self.assertIn("fetch-depth: 0", web)
        validation = web.split("- name: Validate static target", maxsplit=1)[1]
        validation = validation.split("\n      - name:", maxsplit=1)[0]
        self.assertIn("GH_TOKEN: ${{ github.token }}", validation)
        self.assertIn("run: npm run web:check", validation)

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
        self.assertIn(
            "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
            macos_evidence,
        )
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
        self.assertNotIn("/tmp/build-timing-macos-arm64.json", linux)
        self.assertNotIn("browser-trace", linux)
        self.assertNotIn("-macos-arm64", linux)

        self.assertIn("name: Full-source macOS ARM64 AR6 candidate", macos)
        self.assertIn("runs-on: macos-14", macos)
        self.assertIn('test "$(uname -m)" = "arm64"', macos)
        self.assertIn('python-version: "3.11.9"', macos)
        self.assertNotIn('python-version: "3.9.6"', macos)
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
        self.assertIn("/tmp/browser-trace-macos-arm64.json", macos)
        self.assertNotIn("/tmp/build-timing-linux.json", macos)
        self.assertNotIn("-linux-x86_64", macos)
        self.assertEqual(linux.count("/tmp/phase-0r-ar6-v1"), 4)
        self.assertEqual(macos.count("/tmp/phase-0r-ar6-v1"), 6)

    def test_macos_vector_toolchain_is_preflighted_on_release_changes(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        preflight = _workflow_job(
            workflow,
            "release-toolchain-macos",
            "ar6-release-evidence",
        )
        producer = _workflow_job(
            workflow,
            "ar6-release-evidence-macos",
            "infrastructure",
        )

        self.assertIn("name: AR6 release toolchain (pinned macOS ARM64)", preflight)
        self.assertIn("needs.changes.outputs.release == 'true'", preflight)
        self.assertIn("inputs.release_evidence != true", preflight)
        self.assertIn("runs-on: macos-14", preflight)
        self.assertIn("src/pipeline/toolchain/build_macos_tippecanoe.sh", preflight)
        self.assertIn("tippecanoe-darwin-arm64-build-receipt.json", preflight)
        self.assertIn('build_a="${RUNNER_TEMP}/ar6-tools-a"', preflight)
        self.assertIn('build_b="${RUNNER_TEMP}/ar6-tools-b"', preflight)
        self.assertIn('cmp "${build_a}/tippecanoe" "${build_b}/tippecanoe"', preflight)
        self.assertIn(
            'cmp "${build_a}/tippecanoe-decode" "${build_b}/tippecanoe-decode"',
            preflight,
        )
        self.assertIn("src/pipeline/toolchain/build_macos_tippecanoe.sh", producer)

    def test_macos_release_evidence_measures_locked_browser_delivery(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        macos = _workflow_job(
            workflow,
            "ar6-release-evidence-macos",
            "infrastructure",
        )

        build = macos.index("Build full real-source candidate")
        setup_node = macos.index(
            "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"
        )
        measure = macos.index("Measure trusted browser delivery")
        validate = macos.index("Validate browser delivery evidence")
        upload = macos.index("Upload independently built candidate and timing")
        self.assertLess(build, setup_node)
        self.assertLess(
            macos.index("rm -f -- /tmp/ar6-regional-confidence.zip", build),
            setup_node,
        )
        self.assertLess(setup_node, measure)
        self.assertLess(measure, validate)
        self.assertLess(validate, upload)
        self.assertIn("node-version: 20", macos)
        self.assertIn(
            "cache-dependency-path: package-lock.json",
            macos,
        )
        self.assertNotIn("working-directory: src/frontend", macos)
        self.assertIn("run: npm ci", macos)
        self.assertIn(
            "run: ./node_modules/.bin/playwright install chromium",
            macos,
        )
        self.assertNotIn("npx playwright", macos)
        command = (
            "node src/web/scripts/measure-ar6-release.mjs /tmp/phase-0r-ar6-v1 "
            "/tmp/browser-trace-macos-arm64.json"
        )
        self.assertIn(command, macos)
        self.assertIn("test -s /tmp/browser-trace-macos-arm64.json", macos)
        self.assertIn(
            "python scripts/science/validate_ar6_delivery_trace.py",
            macos,
        )
        self.assertIn("--candidate /tmp/phase-0r-ar6-v1", macos)
        self.assertIn("--trace /tmp/browser-trace-macos-arm64.json", macos)
        self.assertIn(
            "--harness src/web/scripts/measure-ar6-release.mjs",
            macos,
        )
        self.assertIn(
            "--build-timing /tmp/build-timing-macos-arm64.json",
            macos,
        )
        self.assertIn("test -s /tmp/delivery-report-macos-arm64.json", macos)
        self.assertIn('.status == "passed"', macos)
        self.assertIn(
            '.candidate.releaseId == "phase-0r-ar6-v1"',
            macos,
        )
        self.assertIn(
            '.trace.path == "browser-trace-macos-arm64.json"',
            macos,
        )
        self.assertIn(
            '.buildTiming.path == "build-timing-macos-arm64.json"',
            macos,
        )
        self.assertIn('.profiles.hardware.architecture == "arm64"', macos)
        self.assertIn('.profiles.browser.engine == "Chromium"', macos)
        self.assertIn("            /tmp/browser-trace-macos-arm64.json", macos)
        self.assertLess(
            macos.index("test -s /tmp/browser-trace-macos-arm64.json"),
            upload,
        )

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
        self.assertIn("      - release-toolchain-macos", gate)

    def test_owner_promotion_is_manual_protected_and_read_only(self) -> None:
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github/workflows/phase-0r-owner-promotion.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("environment: phase-0r-owner-approval", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("pull-requests: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("ref: master", workflow)
        self.assertIn(
            "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1",
            workflow,
        )
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0",
            workflow,
        )
        self.assertIn(
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2",
            workflow,
        )
        self.assertIn('[[ "${GITHUB_RUN_ATTEMPT}" == "1" ]]', workflow)
        self.assertIn("retention-days: 90", workflow)
        action_lines = [
            line.strip() for line in workflow.splitlines() if "uses:" in line
        ]
        self.assertTrue(action_lines)
        self.assertTrue(
            all(
                re.search(r"@[0-9a-f]{40}(?:\s+#\s+v\S+)?$", line)
                for line in action_lines
            )
        )
        self.assertLess(
            workflow.index("Validate protected dispatch boundary"),
            workflow.index("actions/checkout"),
        )

        routes = classify_paths([".github/workflows/phase-0r-owner-promotion.yml"])
        self.assertTrue(routes["pipeline"])
        self.assertTrue(routes["release"])
        self.assertTrue(routes["heavy"])
        self.assertFalse(routes["frontend"])
        self.assertFalse(routes["api"])

        script_routes = classify_paths(
            ["scripts/science/promote_phase_0r_release.py"]
        )
        self.assertTrue(script_routes["pipeline"])
        self.assertTrue(script_routes["release"])
        self.assertTrue(script_routes["heavy"])
        self.assertFalse(script_routes["frontend"])
        self.assertFalse(script_routes["api"])

        delivery_routes = classify_paths(
            ["scripts/science/validate_ar6_delivery_trace.py"]
        )
        self.assertTrue(delivery_routes["pipeline"])
        self.assertTrue(delivery_routes["release"])
        self.assertTrue(delivery_routes["heavy"])

    def test_owner_promotion_exposes_only_reviewed_inputs(self) -> None:
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github/workflows/phase-0r-owner-promotion.yml").read_text(
            encoding="utf-8"
        )
        input_block = workflow[
            workflow.index("    inputs:") : workflow.index("\npermissions:")
        ]

        self.assertEqual(input_block.count("      validation_run_id:"), 1)
        self.assertEqual(input_block.count("      evidence_pr_number:"), 1)
        self.assertEqual(input_block.count("      decision:"), 1)
        for forbidden in (
            "repository:",
            "ref:",
            "workflow:",
            "artifact:",
            "source_sha:",
            "actor:",
            "merged:",
        ):
            self.assertNotIn(forbidden, input_block)

        verifier = (
            root / "src/pipeline/searise_pipeline/release/owner_promotion.py"
        ).read_text(encoding="utf-8")
        self.assertIn('VALIDATION_WORKFLOW = ".github/workflows/ci.yml"', verifier)
        self.assertIn('VALIDATION_JOB_ID = "ar6-release-evidence"', verifier)
        self.assertIn(
            'VALIDATION_JOB_NAME = "Full-source Linux AR6 candidate"', verifier
        )
        self.assertIn(
            'MAC_VALIDATION_JOB_NAME = "Full-source macOS ARM64 AR6 candidate"',
            verifier,
        )
        self.assertIn('REPOSITORY = "artemsemdev/SeaRise-Europe"', verifier)
        self.assertIn('MASTER_REF = "refs/heads/master"', verifier)

    def test_controlled_offline_build_routes_pipeline_and_release_only(self) -> None:
        for path in (
            ".github/workflows/offline-release-controlled.yml",
            "scripts/release/prepare_controlled_offline_inputs.py",
        ):
            with self.subTest(path=path):
                outputs = classify_paths([path])
                self.assertTrue(outputs["pipeline"])
                self.assertTrue(outputs["release"])
                self.assertTrue(outputs["heavy"])
                self.assertFalse(outputs["frontend"])
                self.assertFalse(outputs["api"])
                self.assertFalse(outputs["infrastructure"])
                self.assertFalse(outputs["compose"])

    def test_offline_receipt_example_routes_pipeline_validation(self) -> None:
        outputs = classify_paths(
            ["docs/evidence/fixtures/offline-release-execution-receipt.example.json"]
        )

        self.assertTrue(outputs["pipeline"])
        self.assertFalse(outputs["frontend"])
        self.assertFalse(outputs["api"])
        self.assertFalse(outputs["infrastructure"])
        self.assertFalse(outputs["compose"])

    def test_controlled_offline_build_is_manual_identity_bound_and_offline(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/offline-release-controlled.yml"
        ).read_text(encoding="utf-8")
        dispatch = workflow.split("permissions:", maxsplit=1)[0]
        first_step = workflow.split("      - uses: actions/checkout", maxsplit=1)[0]

        self.assertIn("  workflow_dispatch:", dispatch)
        self.assertNotIn("pull_request:", dispatch)
        self.assertNotIn("push:", dispatch)
        self.assertIn("actions: read", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("environment: phase-1-controlled-offline-build", workflow)
        self.assertIn("regional", dispatch)
        self.assertIn("full-europe", dispatch)
        self.assertIn('[[ "${SOURCE_REVISION}" == "${GITHUB_SHA}" ]]', first_step)
        self.assertIn('[[ "${GITHUB_RUN_ATTEMPT}" == "1" ]]', first_step)
        self.assertIn("input_bundle_sha256:", dispatch)
        self.assertIn("input_run_id:", dispatch)
        self.assertIn("input_artifact_name:", dispatch)
        self.assertIn("persist-credentials: false", workflow)
        self.assertEqual(workflow.count("--network none"), 2)
        self.assertIn('--user "$(id -u):$(id -g)"', workflow)
        self.assertEqual(workflow.count("--read-only"), 2)
        self.assertIn(
            ":/workspace/build-inputs/offline-release/${PROFILE}:ro",
            workflow,
        )
        self.assertIn("publicationAttempted: false", workflow)
        self.assertIn("activationAttempted: false", workflow)
        self.assertNotIn("azure", workflow.lower())
        self.assertNotIn("cloudflare", workflow.lower())
        self.assertNotIn("database", workflow.lower())

        action_lines = [
            line.strip() for line in workflow.splitlines() if "uses:" in line
        ]
        self.assertTrue(action_lines)
        self.assertTrue(
            all(
                re.search(r"@[0-9a-f]{40}(?:\s+#\s+v\S+)?$", line)
                for line in action_lines
            )
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
