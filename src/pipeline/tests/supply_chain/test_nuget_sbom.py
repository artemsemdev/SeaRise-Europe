"""Fail-closed tests for project- and target-specific NuGet CycloneDX SBOMs."""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, cast

import pytest

from searise_pipeline import supply_chain
from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    publish_nuget_sbom,
)
from searise_pipeline.supply_chain.nuget_sbom import (
    generate_nuget_sbom,
    validate_nuget_sbom,
)
from searise_pipeline.supply_chain.sbom import canonical_sbom_bytes

ROOT = Path(__file__).resolve().parents[4]
main = cast(
    Callable[..., int],
    runpy.run_path(str(ROOT / "scripts/release/validate_supply_chain_contract.py"))["main"],
)
FIXTURE = ROOT / "contracts/supply-chain/v1/fixtures/nuget"
PROJECT = FIXTURE / "Fixture.App.xml"
LOCK = FIXTURE / "packages-lock.synthetic.json"
TARGET = "net8.0"
ARTIFACT_ROOT = ROOT / "contracts/supply-chain/v1/sboms/nuget"
MANIFEST = ARTIFACT_ROOT / "manifest.json"
REAL_TARGETS = {
    "searise-api-net8.0": ("SeaRise.Api", "production-api", 48),
    "searise-application-net8.0": ("SeaRise.Application", "library", 3),
    "searise-domain-net8.0": ("SeaRise.Domain", "library", 0),
    "searise-infrastructure-net8.0": ("SeaRise.Infrastructure", "library", 17),
}


@pytest.fixture
def historical_legacy_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "historical-repository"
    profile = json.loads(
        (ROOT / "contracts/supply-chain/v2/static-target-profile.json").read_bytes()
    )
    commit = profile["historicalEvidence"]["gitAuthority"]["commit"]
    for directory in [*{value[0] for value in REAL_TARGETS.values()}, "SeaRise.Api.Tests"]:
        for name in (f"{directory}.csproj", "packages.lock.json"):
            logical = f"src/api/{directory}/{name}"
            target = repository / logical
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                subprocess.run(
                    ["git", "show", f"{commit}:{logical}"],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                ).stdout
            )
    shutil.copytree(
        ROOT / "contracts/supply-chain/v1",
        repository / "contracts/supply-chain/v1",
    )
    return repository


def _generate(
    project: Path = PROJECT,
    lock: Path = LOCK,
    *,
    repository: Path = ROOT,
    target: str = TARGET,
) -> dict[str, Any]:
    return generate_nuget_sbom(
        project,
        lock,
        repository_root=repository,
        target_framework=target,
    )


def _properties(component: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["value"] for item in component["properties"]}


def _components(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {component["name"].casefold(): component for component in document["components"]}


def _relationships(document: dict[str, Any]) -> dict[str, list[str]]:
    return {item["ref"]: item["dependsOn"] for item in document["dependencies"]}


def _copy_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository = tmp_path / "repository"
    destination = repository / "contracts/supply-chain/v1/fixtures/nuget"
    destination.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE, destination)
    return repository, destination / PROJECT.name, destination / LOCK.name


def _write_lock(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _write_sbom(path: Path, document: dict[str, Any]) -> None:
    path.write_bytes(canonical_sbom_bytes(document))


def test_graph_preserves_types_ranges_edges_and_only_lock_integrity() -> None:
    document = _generate()
    components = _components(document)
    relationships = _relationships(document)
    alpha, bravo, library = (components[name] for name in ("alpha", "bravo", "fixture.library"))

    assert document["specVersion"] == "1.7"
    assert alpha["purl"] == alpha["bom-ref"] == "pkg:nuget/Alpha@1.0.0"
    assert alpha["hashes"] == [{"alg": "SHA-512", "content": "61" * 64}]
    assert bravo["hashes"] == [{"alg": "SHA-512", "content": "62" * 64}]
    alpha_properties = _properties(alpha)
    assert alpha_properties["org.searise.sbom.nuget.dependency-type"] == "Direct"
    assert alpha_properties["org.searise.sbom.nuget.requested"] == "[1.0.0, )"
    assert alpha_properties["org.searise.sbom.nuget.manifest-version"] == "1.0.0"
    assert _properties(bravo)["org.searise.sbom.nuget.dependency-type"] == "Transitive"
    assert "version" not in library and "hashes" not in library and "purl" not in library
    assert _properties(library)["org.searise.sbom.nuget.project.integrity"] == (
        "not-available-in-packages-lock-v1"
    )
    root = document["metadata"]["component"]["bom-ref"]
    assert relationships[root] == sorted([alpha["bom-ref"], library["bom-ref"]])
    assert relationships[alpha["bom-ref"]] == [bravo["bom-ref"]]
    assert relationships[library["bom-ref"]] == [bravo["bom-ref"]]
    assert relationships[bravo["bom-ref"]] == []


def test_root_binds_exact_authority_target_kind_and_non_claims() -> None:
    root = _generate()["metadata"]["component"]
    properties = _properties(root)
    assert root["name"] == "Fixture.App" and root["type"] == "application"
    assert properties["org.searise.sbom.nuget.project.manifest.path"] == (
        "contracts/supply-chain/v1/fixtures/nuget/Fixture.App.xml"
    )
    assert (
        properties["org.searise.sbom.nuget.project.manifest.sha256"]
        == hashlib.sha256(PROJECT.read_bytes()).hexdigest()
    )
    assert (
        properties["org.searise.sbom.nuget.lock.sha256"]
        == hashlib.sha256(LOCK.read_bytes()).hexdigest()
    )
    assert properties["org.searise.sbom.nuget.target-framework"] == TARGET
    assert properties["org.searise.sbom.nuget.project.kind"] == "production-api"
    assert properties["org.searise.sbom.production-claim"] == "false"
    assert properties["org.searise.sbom.candidate-inclusion"] == "unclaimed"
    assert properties["org.searise.sbom.vulnerability-completeness"] == "unclaimed"
    assert properties["org.searise.sbom.license-completeness"] == "unclaimed"


@pytest.mark.parametrize(
    ("directory", "count", "kind"),
    [
        ("SeaRise.Api", 48, "production-api"),
        ("SeaRise.Api.Tests", 90, "test"),
        ("SeaRise.Application", 3, "library"),
        ("SeaRise.Domain", 0, "library"),
        ("SeaRise.Infrastructure", 17, "library"),
    ],
)
def test_all_real_project_locks_have_supported_truthful_graphs(
    historical_legacy_repository: Path, directory: str, count: int, kind: str
) -> None:
    project_root = historical_legacy_repository / "src/api" / directory
    document = _generate(
        project_root / f"{directory}.csproj",
        project_root / "packages.lock.json",
        repository=historical_legacy_repository,
    )
    assert len(document["components"]) == count
    assert (
        _properties(document["metadata"]["component"])["org.searise.sbom.nuget.project.kind"]
        == kind
    )


def test_generation_and_exact_regeneration_are_byte_stable(tmp_path: Path) -> None:
    content = canonical_sbom_bytes(_generate())
    assert canonical_sbom_bytes(_generate()) == content
    output = tmp_path / "nuget.cdx.json"
    output.write_bytes(content)
    validated = validate_nuget_sbom(
        output,
        PROJECT,
        LOCK,
        repository_root=ROOT,
        target_framework=TARGET,
    )
    assert canonical_sbom_bytes(validated) == content


@pytest.mark.parametrize("target", ["missing", "", True, 1, None])
def test_target_framework_must_be_explicit_and_present(target: object) -> None:
    with pytest.raises(SupplyChainContractError, match="target framework"):
        _generate(target=target)  # type: ignore[arg-type]


def _remove_direct(lock: dict[str, Any]) -> None:
    del lock["dependencies"][TARGET]["Alpha"]


def _remove_project(lock: dict[str, Any]) -> None:
    del lock["dependencies"][TARGET]["fixture.library"]


def _break_hash(lock: dict[str, Any]) -> None:
    lock["dependencies"][TARGET]["Alpha"]["contentHash"] = "not-base64"


def _add_casefold_duplicate(lock: dict[str, Any]) -> None:
    lock["dependencies"][TARGET]["Alpha"]["dependencies"]["bravo"] = "[2.0.0, )"


def _add_unreachable(lock: dict[str, Any]) -> None:
    lock["dependencies"][TARGET]["Delta"] = {
        "type": "Transitive",
        "resolved": "4.0.0",
        "contentHash": lock["dependencies"][TARGET]["Alpha"]["contentHash"],
    }


def _bool_version(lock: dict[str, Any]) -> None:
    lock["version"] = True


@pytest.mark.parametrize(
    "mutation",
    [
        _remove_direct,
        _remove_project,
        _break_hash,
        _add_casefold_duplicate,
        _add_unreachable,
        _bool_version,
    ],
    ids=["direct-parity", "project-parity", "hash", "casefold-duplicate", "unreachable", "bool"],
)
def test_lock_drift_fails_closed(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    repository, project, lock_path = _copy_fixture(tmp_path)
    lock = json.loads(lock_path.read_bytes())
    mutation(lock)
    _write_lock(lock_path, lock)
    with pytest.raises(SupplyChainContractError):
        _generate(project, lock_path, repository=repository)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("<TargetFramework>net8.0</TargetFramework>", "<TargetFramework>net9.0</TargetFramework>"),
        ('<PackageReference Include="Alpha" Version="1.0.0" />', ""),
        ('Include="Alpha"', 'Include="Alpha" Condition="true"'),
    ],
)
def test_project_manifest_drift_fails_closed(tmp_path: Path, old: str, new: str) -> None:
    repository, project, lock_path = _copy_fixture(tmp_path)
    project.write_text(project.read_text().replace(old, new), encoding="utf-8")
    with pytest.raises(SupplyChainContractError):
        _generate(project, lock_path, repository=repository)


def _remove_component(document: dict[str, Any]) -> None:
    document["components"].pop()


def _remove_edge(document: dict[str, Any]) -> None:
    document["dependencies"][0]["dependsOn"] = []


def _forge_hash(document: dict[str, Any]) -> None:
    next(item for item in document["components"] if "hashes" in item)["hashes"][0]["content"] = (
        "0" * 128
    )


def _forge_claim(document: dict[str, Any]) -> None:
    properties = document["metadata"]["component"]["properties"]
    next(item for item in properties if item["name"].endswith("production-claim"))["value"] = "true"


@pytest.mark.parametrize("mutation", [_remove_component, _remove_edge, _forge_hash, _forge_claim])
def test_sbom_graph_integrity_and_claim_drift_fail_exact_regeneration(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    document = copy.deepcopy(_generate())
    mutation(document)
    output = tmp_path / "mutated.json"
    _write_sbom(output, document)
    with pytest.raises(SupplyChainContractError):
        validate_nuget_sbom(
            output,
            PROJECT,
            LOCK,
            repository_root=ROOT,
            target_framework=TARGET,
        )


@pytest.mark.parametrize(
    "content",
    [b'{"bomFormat":"CycloneDX"}', b'{"a":1,"a":1}\n', b'{"value":NaN}\n', b"[]\n", b"{\xff}\n"],
)
def test_noncanonical_duplicate_or_malformed_sbom_bytes_fail_closed(
    tmp_path: Path, content: bytes
) -> None:
    output = tmp_path / "invalid.json"
    output.write_bytes(content)
    with pytest.raises(SupplyChainContractError):
        validate_nuget_sbom(
            output,
            PROJECT,
            LOCK,
            repository_root=ROOT,
            target_framework=TARGET,
        )


def test_authority_mutation_invalidates_an_existing_sbom(tmp_path: Path) -> None:
    repository, project, lock_path = _copy_fixture(tmp_path)
    output = tmp_path / "nuget.json"
    _write_sbom(output, _generate(project, lock_path, repository=repository))
    project.write_text(project.read_text() + "\n", encoding="utf-8")
    with pytest.raises(SupplyChainContractError, match="authority"):
        validate_nuget_sbom(
            output,
            project,
            lock_path,
            repository_root=repository,
            target_framework=TARGET,
        )


@pytest.mark.parametrize("name", ["project", "lock", "parent"])
def test_symlinked_authority_paths_fail_closed(tmp_path: Path, name: str) -> None:
    repository, project, lock_path = _copy_fixture(tmp_path)
    if name == "parent":
        parent, real = project.parent, project.parent.with_name("nuget-real")
        parent.rename(real)
        parent.symlink_to(real, target_is_directory=True)
    else:
        path = project if name == "project" else lock_path
        real = path.with_suffix(path.suffix + ".real")
        path.rename(real)
        path.symlink_to(real)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        _generate(project, lock_path, repository=repository)


def test_outside_non_sibling_and_symlinked_sbom_paths_fail_closed(tmp_path: Path) -> None:
    repository, project, lock_path = _copy_fixture(tmp_path)
    with pytest.raises(SupplyChainContractError, match="beneath"):
        _generate(PROJECT, lock_path, repository=repository)
    with pytest.raises(SupplyChainContractError, match="sibling"):
        other = repository / "other"
        other.mkdir()
        moved_lock = other / lock_path.name
        lock_path.rename(moved_lock)
        _generate(project, moved_lock, repository=repository)
    real = tmp_path / "real.json"
    _write_sbom(real, _generate())
    alias = tmp_path / "alias.json"
    alias.symlink_to(real)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        validate_nuget_sbom(
            alias,
            PROJECT,
            LOCK,
            repository_root=ROOT,
            target_framework=TARGET,
        )


def test_real_artifact_manifest_binds_exact_authorities_and_non_claims(
    historical_legacy_repository: Path,
) -> None:
    repository = historical_legacy_repository
    artifact_root = repository / "contracts/supply-chain/v1/sboms/nuget"
    manifest = json.loads((artifact_root / "manifest.json").read_bytes())
    assert set(manifest) == {
        "artifacts",
        "candidateAttachmentStatus",
        "excludedTargets",
        "manifestId",
        "productionClaim",
        "schemaVersion",
    }
    assert manifest["schemaVersion"] == "1.0.0"
    assert manifest["manifestId"] == "searise-nuget-sbom-artifacts-v1"
    assert manifest["candidateAttachmentStatus"] == "not-attached"
    assert manifest["productionClaim"] is False

    artifacts = {entry["id"]: entry for entry in manifest["artifacts"]}
    assert set(artifacts) == set(REAL_TARGETS)
    for identifier, (directory, kind, component_count) in REAL_TARGETS.items():
        entry = artifacts[identifier]
        assert set(entry) == {
            "artifactPath",
            "artifactSha256",
            "componentCount",
            "id",
            "lockPath",
            "lockSha256",
            "projectKind",
            "projectPath",
            "projectSha256",
            "targetFramework",
        }
        project = repository / entry["projectPath"]
        lock = repository / entry["lockPath"]
        artifact = repository / entry["artifactPath"]
        assert project == repository / f"src/api/{directory}/{directory}.csproj"
        assert lock == repository / f"src/api/{directory}/packages.lock.json"
        assert artifact == artifact_root / f"{identifier}.cdx.json"
        assert hashlib.sha256(project.read_bytes()).hexdigest() == entry["projectSha256"]
        assert hashlib.sha256(lock.read_bytes()).hexdigest() == entry["lockSha256"]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == entry["artifactSha256"]
        assert entry["targetFramework"] == TARGET
        assert entry["projectKind"] == kind
        assert entry["componentCount"] == component_count

        document = validate_nuget_sbom(
            artifact,
            project,
            lock,
            repository_root=repository,
            target_framework=TARGET,
        )
        properties = _properties(document["metadata"]["component"])
        assert len(document["components"]) == component_count
        assert artifact.read_bytes() == canonical_sbom_bytes(document)
        assert properties["org.searise.sbom.nuget.project.kind"] == kind
        assert properties["org.searise.sbom.production-claim"] == "false"
        assert properties["org.searise.sbom.candidate-inclusion"] == "unclaimed"
        assert properties["org.searise.sbom.vulnerability-completeness"] == "unclaimed"
        assert properties["org.searise.sbom.license-completeness"] == "unclaimed"


def test_test_project_is_exactly_recorded_but_not_published(
    historical_legacy_repository: Path,
) -> None:
    repository = historical_legacy_repository
    artifact_root = repository / "contracts/supply-chain/v1/sboms/nuget"
    excluded = json.loads((artifact_root / "manifest.json").read_bytes())["excludedTargets"]
    assert len(excluded) == 1
    entry = excluded[0]
    assert set(entry) == {
        "lockPath",
        "lockSha256",
        "projectKind",
        "projectPath",
        "projectSha256",
        "reason",
        "targetFramework",
    }
    assert entry["projectPath"] == "src/api/SeaRise.Api.Tests/SeaRise.Api.Tests.csproj"
    assert entry["lockPath"] == "src/api/SeaRise.Api.Tests/packages.lock.json"
    assert entry["projectKind"] == "test" and entry["targetFramework"] == TARGET
    assert entry["reason"] == "Test project excluded from candidate production attachment."
    assert (
        hashlib.sha256((repository / entry["projectPath"]).read_bytes()).hexdigest()
        == entry["projectSha256"]
    )
    assert (
        hashlib.sha256((repository / entry["lockPath"]).read_bytes()).hexdigest()
        == entry["lockSha256"]
    )
    assert not (artifact_root / "searise-api-tests-net8.0.cdx.json").exists()


def test_public_api_publishes_exact_real_target_once(
    tmp_path: Path, historical_legacy_repository: Path
) -> None:
    repository = historical_legacy_repository
    directory = "SeaRise.Domain"
    project = repository / f"src/api/{directory}/{directory}.csproj"
    lock = repository / f"src/api/{directory}/packages.lock.json"
    output = tmp_path / "domain.cdx.json"
    document = publish_nuget_sbom(
        output,
        project,
        lock,
        repository_root=repository,
        target_framework=TARGET,
    )

    assert output.read_bytes() == (
        repository / "contracts/supply-chain/v1/sboms/nuget/searise-domain-net8.0.cdx.json"
    ).read_bytes()
    assert output.read_bytes() == canonical_sbom_bytes(document)
    assert supply_chain.generate_nuget_sbom
    assert supply_chain.publish_nuget_sbom
    assert supply_chain.validate_nuget_sbom
    with pytest.raises(SupplyChainContractError, match="already exists"):
        publish_nuget_sbom(
            output,
            project,
            lock,
            repository_root=repository,
            target_framework=TARGET,
        )


def test_cli_generates_and_validates_one_explicit_real_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    historical_legacy_repository: Path,
) -> None:
    repository = historical_legacy_repository
    directory = "SeaRise.Domain"
    output = tmp_path / "domain.cdx.json"
    common = [
        "--project",
        str(repository / f"src/api/{directory}/{directory}.csproj"),
        "--lock",
        str(repository / f"src/api/{directory}/packages.lock.json"),
        "--repository-root",
        str(repository),
        "--target-framework",
        TARGET,
    ]
    assert main(["nuget-sbom", *common, "--output", str(output)]) == 0
    assert f"generated 0 NuGet components for {TARGET}" in capsys.readouterr().out
    assert output.read_bytes() == (
        repository / "contracts/supply-chain/v1/sboms/nuget/searise-domain-net8.0.cdx.json"
    ).read_bytes()
    assert main(["nuget-sbom-validate", *common, "--sbom", str(output)]) == 0
    assert f"validated 0 NuGet components for {TARGET}" in capsys.readouterr().out


def test_missing_mutated_and_symlinked_real_artifacts_fail_closed(
    tmp_path: Path, historical_legacy_repository: Path
) -> None:
    repository = historical_legacy_repository
    directory = "SeaRise.Application"
    project = repository / f"src/api/{directory}/{directory}.csproj"
    lock = repository / f"src/api/{directory}/packages.lock.json"
    arguments = {
        "repository_root": repository,
        "target_framework": TARGET,
    }
    with pytest.raises(SupplyChainContractError):
        validate_nuget_sbom(tmp_path / "missing.json", project, lock, **arguments)

    document = json.loads(
        (
            repository
            / "contracts/supply-chain/v1/sboms/nuget/searise-application-net8.0.cdx.json"
        ).read_bytes()
    )
    _forge_claim(document)
    mutated = tmp_path / "mutated.json"
    _write_sbom(mutated, document)
    with pytest.raises(SupplyChainContractError, match="authority"):
        validate_nuget_sbom(mutated, project, lock, **arguments)

    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(SupplyChainContractError, match="must not be a symlink"):
        publish_nuget_sbom(
            alias_parent / "sbom.json",
            project,
            lock,
            **arguments,
        )
