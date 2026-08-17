"""Fail-closed tests for the static-browser supply-chain transition profile."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    discover_dependency_inputs,
    generate_npm_sbom,
    validate_static_target_profile,
)

ROOT = Path(__file__).resolve().parents[4]
PROFILE = ROOT / "contracts/supply-chain/v2/static-target-profile.json"
SCHEMA = ROOT / "contracts/supply-chain/v2/static-target-profile.schema.json"


def _load(path: Path = PROFILE) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def _write(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _item(document: dict[str, Any], path: str) -> dict[str, str]:
    return next(
        item
        for component in document["components"]
        for item in component["inputs"]
        if item["path"] == path
    )


def _copy_active_authority(destination: Path) -> None:
    for component in _load()["components"]:
        for item in component["inputs"]:
            target = destination / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / item["path"], target)
    for selector in _load()["activation"]["pendingSelectors"]:
        if selector["selector"] != "path-exists":
            continue
        source = ROOT / selector["path"]
        target = destination / selector["path"]
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _refresh_hash(document: dict[str, Any], repository: Path, path: str) -> None:
    _item(document, path)["sha256"] = hashlib.sha256((repository / path).read_bytes()).hexdigest()


def _remove_issue_selectors(
    document: dict[str, Any],
    repository: Path,
    issue: int,
) -> None:
    changed_files: set[str] = set()
    for selector in list(document["activation"]["pendingSelectors"]):
        if selector["issue"] != issue:
            continue
        target = repository / selector["path"]
        if selector["selector"] == "path-exists":
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        elif not selector["id"].startswith("pipeline-"):
            value = target.read_text(encoding="utf-8")
            _kind, _separator, expression = selector["selector"].partition(":")
            words = expression.split()
            pattern = (
                r"(?i)(?<![a-z0-9])"
                + r"[^a-z0-9]+".join(map(re.escape, words))
                + r"(?![a-z0-9])"
            )
            target.write_text(
                re.sub(pattern, "removed-legacy-token", value),
                encoding="utf-8",
            )
            changed_files.add(selector["path"])
    document["activation"]["pendingSelectors"] = [
        selector
        for selector in document["activation"]["pendingSelectors"]
        if selector["issue"] != issue
    ]
    document["activation"]["blockingIssues"] = sorted(
        {selector["issue"] for selector in document["activation"]["pendingSelectors"]}
    )
    document["activation"]["status"] = (
        "pending-legacy-removal"
        if document["activation"]["pendingSelectors"]
        else "active"
    )
    for path in changed_files:
        _refresh_hash(document, repository, path)


def _migrate_issue_71_python_authority(document: dict[str, Any], repository: Path) -> None:
    target_path = (
        repository
        / "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt"
    )
    target_lines = [
        line.strip()
        for line in target_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    dependencies = [line for line in target_lines if not line.lower().startswith("pytest")]
    pytest_requirement = next(line for line in target_lines if line.lower().startswith("pytest"))
    pyproject_path = repository / "src/pipeline/pyproject.toml"
    pyproject = pyproject_path.read_text(encoding="utf-8")
    dependency_block = "dependencies = [\n" + "".join(
        f'    "{line}",\n' for line in dependencies
    ) + "]"
    dev_block = f'dev = [\n    "{pytest_requirement}",\n]'
    pyproject = re.sub(
        r"(?ms)^dependencies\s*=\s*\[.*?^\]",
        dependency_block,
        pyproject,
        count=1,
    )
    pyproject = re.sub(r"(?ms)^dev\s*=\s*\[.*?^\]", dev_block, pyproject, count=1)
    pyproject_path.write_text(pyproject, encoding="utf-8")
    requirements_path = repository / "src/pipeline/requirements-pipeline.txt"
    requirements_path.write_text("\n".join(target_lines) + "\n", encoding="utf-8")

    pending = next(
        component
        for component in document["components"]
        if component["id"] == "pending-legacy-python-authorities"
    )
    contributor = next(
        component
        for component in document["components"]
        if component["id"] == "pipeline-python-contributor"
    )
    contributor["inputs"].extend(pending["inputs"])
    contributor["inputs"].sort(key=lambda item: item["path"])
    document["components"].remove(pending)
    for path in ("src/pipeline/pyproject.toml", "src/pipeline/requirements-pipeline.txt"):
        _refresh_hash(document, repository, path)


def test_profile_schema_passes_draft_2020_12_metaschema() -> None:
    Draft202012Validator.check_schema(_load(SCHEMA))


def test_npm_sbom_rejects_unreviewed_scope() -> None:
    with pytest.raises(SupplyChainContractError, match="unsupported npm SBOM scope"):
        generate_npm_sbom(
            ROOT / "package-lock.json",
            repository_root=ROOT,
            logical_path="package-lock.json",
            scope="unreviewed-runtime",
        )


def test_checked_in_profile_validates_only_the_static_target() -> None:
    document = validate_static_target_profile(PROFILE, repository_root=ROOT)
    paths = {
        item["path"]
        for component in document["components"]
        for item in component["inputs"]
    }

    assert document["target"] == "static-browser"
    assert document["productionClaim"] is False
    assert document["activation"]["status"] == "pending-legacy-removal"
    assert document["activation"]["blockingIssues"] == [70, 71, 72]
    assert {
        selector["id"]: selector["issue"]
        for selector in document["activation"]["pendingSelectors"]
    } == {
        "ci-legacy-api": 71,
        "ci-legacy-compose": 72,
        "ci-legacy-compose-command": 72,
        "ci-legacy-dotnet": 71,
        "ci-legacy-dotnet-command": 71,
        "ci-legacy-frontend": 70,
        "codeql-legacy-csharp": 71,
        "codeql-legacy-dotnet": 71,
        "legacy-api-tree": 71,
        "legacy-blob-seed-tree": 72,
        "legacy-compose-file": 72,
        "legacy-compose-smoke": 72,
        "legacy-db-geography": 71,
        "legacy-db-init": 71,
        "legacy-frontend-tree": 70,
        "legacy-solution-file": 71,
        "pipeline-pyproject-azure": 71,
        "pipeline-pyproject-postgis": 71,
        "pipeline-requirements-azure": 71,
        "pipeline-requirements-postgis": 71,
    }
    assert document["historicalEvidence"] == {
        "path": "contracts/supply-chain/v1",
        "status": "immutable-phase-1-history",
    }
    assert {"package.json", "package-lock.json", "src/web/package.json"} <= paths
    assert "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json" in paths
    assert "contracts/supply-chain/v1/sboms/frontend-npm.cdx.json" not in paths
    assert "src/pipeline/pyproject.toml" in paths
    assert "src/pipeline/requirements-pipeline.txt" in paths
    assert (
        "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt"
        not in discover_dependency_inputs()
    )
    assert not any(
        path.startswith(("src/api/", "src/frontend/", "infra/blob-seed/"))
        or Path(path).name.startswith(("compose.", "docker-compose."))
        for path in paths
    )


def test_profile_reconstructs_hash_bound_readiness_authority(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)

    validated = validate_static_target_profile(PROFILE, repository_root=repository)

    assert len(validated["components"]) == 13
    assert validated["activation"]["status"] == "pending-legacy-removal"
    assert validated["activation"]["blockingIssues"] == [70, 71, 72]


def test_profile_rejects_legacy_runtime_as_an_active_input(tmp_path: Path) -> None:
    document = copy.deepcopy(_load())
    legacy = ROOT / "src/frontend/package.json"
    component = next(item for item in document["components"] if item["id"] == "static-web-npm")
    component["inputs"].append(
        {
            "path": "src/frontend/package.json",
            "role": "manifest",
            "sha256": hashlib.sha256(legacy.read_bytes()).hexdigest(),
        }
    )
    component["inputs"].sort(key=lambda item: item["path"])

    with pytest.raises(SupplyChainContractError, match="legacy runtime"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


def test_profile_rejects_missing_required_static_input(tmp_path: Path) -> None:
    document = copy.deepcopy(_load())
    component = next(item for item in document["components"] if item["id"] == "static-web-npm")
    component["inputs"] = [
        item for item in component["inputs"] if item["path"] != "src/web/package.json"
    ]

    with pytest.raises(SupplyChainContractError, match="input set drifted"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


def test_profile_rejects_changed_authority_bytes(tmp_path: Path) -> None:
    document = copy.deepcopy(_load())
    _item(document, "package.json")["sha256"] = "f" * 64

    with pytest.raises(SupplyChainContractError, match="SHA-256 mismatch: package.json"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


def test_profile_cannot_claim_active_while_legacy_selectors_remain(tmp_path: Path) -> None:
    document = copy.deepcopy(_load())
    document["activation"] = {
        "status": "active",
        "blockingIssues": [],
        "pendingSelectors": [],
    }

    with pytest.raises(SupplyChainContractError, match="activation does not match"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


def test_profile_detects_pep508_legacy_name_with_alternate_whitespace(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    pyproject_path = repository / "src/pipeline/pyproject.toml"
    pyproject_path.write_text(
        pyproject_path.read_text(encoding="utf-8").replace(
            "azure-storage-blob>=12.19,<13.0",
            "azure_storage_blob >= 12.19, < 13.0",
        ),
        encoding="utf-8",
    )
    document = copy.deepcopy(_load())
    _refresh_hash(document, repository, "src/pipeline/pyproject.toml")

    validated = validate_static_target_profile(
        _write(tmp_path / "profile.json", document),
        repository_root=repository,
    )

    assert any(
        selector["id"] == "pipeline-pyproject-azure"
        for selector in validated["activation"]["pendingSelectors"]
    )


@pytest.mark.parametrize(
    ("path", "selector_id", "needle", "replacement", "injected"),
    [
        (
            ".github/workflows/ci.yml",
            "ci-legacy-api",
            "src/api",
            "${LEGACY_API_PATH}",
            'LEGACY_API_PATH: "src\t/\n  api"',
        ),
        (
            ".github/workflows/codeql.yml",
            "codeql-legacy-csharp",
            "csharp",
            "${LEGACY_LANGUAGE}",
            'LEGACY_LANGUAGE: "csharp"',
        ),
        (
            ".github/workflows/ci.yml",
            "ci-legacy-compose-command",
            "docker compose",
            "${CONTAINER_CLI}",
            'CONTAINER_CLI: "docker\n  compose"',
        ),
    ],
)
def test_workflow_scanner_resists_whitespace_and_env_indirection(
    tmp_path: Path,
    path: str,
    selector_id: str,
    needle: str,
    replacement: str,
    injected: str,
) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    workflow = repository / path
    value = workflow.read_text(encoding="utf-8")
    assert needle in value
    workflow.write_text(value.replace(needle, replacement) + f"\n{injected}\n", encoding="utf-8")
    document = copy.deepcopy(_load())
    _refresh_hash(document, repository, path)

    validated = validate_static_target_profile(
        _write(tmp_path / "profile.json", document),
        repository_root=repository,
    )

    assert any(
        selector["id"] == selector_id
        for selector in validated["activation"]["pendingSelectors"]
    )


def test_profile_accepts_exact_partial_selector_shrink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    document = copy.deepcopy(_load())
    _remove_issue_selectors(document, repository, 70)

    validated = validate_static_target_profile(
        _write(tmp_path / "profile.json", document),
        repository_root=repository,
    )

    assert validated["activation"]["blockingIssues"] == [71, 72]
    assert all(
        selector["issue"] != 70
        for selector in validated["activation"]["pendingSelectors"]
    )


def test_issue_71_migration_requires_exact_static_contributor_parity(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    document = copy.deepcopy(_load())
    _migrate_issue_71_python_authority(document, repository)
    _remove_issue_selectors(document, repository, 71)

    validated = validate_static_target_profile(
        _write(tmp_path / "profile.json", document),
        repository_root=repository,
    )

    assert validated["activation"]["blockingIssues"] == [70, 72]
    assert all(
        component["id"] != "pending-legacy-python-authorities"
        for component in validated["components"]
    )


def test_profile_becomes_active_only_after_final_tracked_absence(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    document = copy.deepcopy(_load())
    _migrate_issue_71_python_authority(document, repository)
    for issue in (70, 71, 72):
        _remove_issue_selectors(document, repository, issue)

    validated = validate_static_target_profile(
        _write(tmp_path / "profile.json", document),
        repository_root=repository,
    )

    assert validated["activation"] == {
        "status": "active",
        "blockingIssues": [],
        "pendingSelectors": [],
    }
    assert not any(
        (repository / path).exists()
        for path in (
            "src/api",
            "src/frontend",
            "infra/blob-seed",
            "docker-compose.yml",
            "scripts/compose-smoke.sh",
            "SeaRise Europe.sln",
            "infra/db/init.sql",
            "infra/db/init-geography.sql",
        )
    )


def test_broken_symlink_cannot_satisfy_active_absence(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    document = copy.deepcopy(_load())
    _migrate_issue_71_python_authority(document, repository)
    for issue in (70, 71, 72):
        _remove_issue_selectors(document, repository, issue)
    geography = repository / "infra/db/init-geography.sql"
    geography.parent.mkdir(parents=True, exist_ok=True)
    geography.symlink_to("missing-init-geography.sql")

    with pytest.raises(SupplyChainContractError, match="activation does not match"):
        validate_static_target_profile(
            _write(tmp_path / "profile.json", document),
            repository_root=repository,
        )


@pytest.mark.parametrize("mutation", ["component", "role"])
def test_profile_rejects_input_owner_or_role_drift(tmp_path: Path, mutation: str) -> None:
    document = copy.deepcopy(_load())
    source = next(item for item in document["components"] if item["id"] == "static-web-npm")
    item = next(item for item in source["inputs"] if item["path"] == "src/web/package.json")
    if mutation == "role":
        item["role"] = "lock"
    else:
        source["inputs"].remove(item)
        target = next(
            component
            for component in document["components"]
            if component["id"] == "pipeline-python-contributor"
        )
        target["inputs"].append(item)
        target["inputs"].sort(key=lambda candidate: candidate["path"])

    with pytest.raises(SupplyChainContractError, match="owner or role drifted"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


def test_profile_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    duplicate = PROFILE.read_text(encoding="utf-8").replace(
        '  "schemaVersion": "2.0.0",',
        '  "schemaVersion": "2.0.0",\n  "schemaVersion": "2.0.0",',
        1,
    )
    path = tmp_path / "profile.json"
    path.write_text(duplicate, encoding="utf-8")

    with pytest.raises(SupplyChainContractError, match="duplicate static supply-chain profile key"):
        validate_static_target_profile(path)


def test_profile_rejects_symlinked_authority(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    package = repository / "package.json"
    real = repository / "package.real.json"
    package.rename(real)
    package.symlink_to(real.name)

    with pytest.raises(SupplyChainContractError, match="must not use symlinks: package.json"):
        validate_static_target_profile(PROFILE, repository_root=repository)


def test_profile_loads_its_bound_schema_from_repository_root(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    (repository / "contracts/supply-chain/v2/static-target-profile.schema.json").unlink()

    with pytest.raises(SupplyChainContractError, match="outside or missing"):
        validate_static_target_profile(PROFILE, repository_root=repository)


def test_profile_rejects_repository_schema_hash_drift(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    schema_path = repository / "contracts/supply-chain/v2/static-target-profile.schema.json"
    schema = json.loads(schema_path.read_bytes())
    schema["description"] = "Unreviewed but structurally valid schema mutation."
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(SupplyChainContractError, match="SHA-256 mismatch.*profile.schema"):
        validate_static_target_profile(PROFILE, repository_root=repository)


def test_profile_rejects_web_manifest_lock_drift(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    manifest_path = repository / "src/web/package.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["dependencies"]["react"] = "0.0.0"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    document = copy.deepcopy(_load())
    _item(document, "src/web/package.json")["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()

    with pytest.raises(SupplyChainContractError, match="differs from its exact lock workspace"):
        validate_static_target_profile(
            _write(tmp_path / "profile.json", document),
            repository_root=repository,
        )


@pytest.mark.parametrize("legacy_package", ["azure-storage-blob", "psycopg2-binary"])
def test_profile_rejects_legacy_python_packages(
    tmp_path: Path,
    legacy_package: str,
) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    manifest_path = (
        repository
        / "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt"
    )
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + f"{legacy_package}>=1,<99\n",
        encoding="utf-8",
    )
    document = copy.deepcopy(_load())
    _item(
        document,
        "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt",
    )["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(SupplyChainContractError, match="legacy Python packages"):
        validate_static_target_profile(
            _write(tmp_path / "profile.json", document),
            repository_root=repository,
        )


@pytest.mark.parametrize("mutation", ["next-component", "frontend-workspace"])
def test_profile_rejects_legacy_npm_graph_entries(tmp_path: Path, mutation: str) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    sbom_path = repository / "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json"
    sbom = json.loads(sbom_path.read_bytes())
    if mutation == "next-component":
        sbom["components"].append({"type": "library", "name": "next", "version": "15.0.0"})
    else:
        properties = sbom["metadata"]["component"]["properties"]
        next(item for item in properties if item["name"].endswith("workspace.path"))["value"] = (
            "src/frontend"
        )
    sbom_path.write_text(json.dumps(sbom, separators=(",", ":")) + "\n", encoding="utf-8")
    document = copy.deepcopy(_load())
    _item(document, "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json")[
        "sha256"
    ] = hashlib.sha256(sbom_path.read_bytes()).hexdigest()

    with pytest.raises(SupplyChainContractError, match="Next.js or src/frontend"):
        validate_static_target_profile(
            _write(tmp_path / "profile.json", document),
            repository_root=repository,
        )
