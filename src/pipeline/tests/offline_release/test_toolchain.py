"""Contracts for the pinned, network-isolated offline builder image."""

from __future__ import annotations

from pathlib import Path

from searise_pipeline.offline_release import BuildProfile, load_profile_definition

REPO_ROOT = Path(__file__).parents[4]
PROFILE_ROOT = REPO_ROOT / "src/pipeline/offline_release/profiles"
DOCKERFILE = REPO_ROOT / "src/pipeline/offline_release/Dockerfile"
IGNORE = REPO_ROOT / "src/pipeline/offline_release/Dockerfile.dockerignore"
BASE_DIGEST = "a8f8fbe1a0edc9e4dddafa64ba73f7e04be7be5ebc23f332362e779e0a2e4e52"


def test_builder_image_pins_base_runtime_lock_and_deterministic_environment() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert text.splitlines()[0] == (
        "FROM python:3.11.15-bookworm@sha256:" + BASE_DIGEST
    )
    assert "--only-binary=:all:" in text
    assert "--require-hashes" in text
    assert "PYTHONHASHSEED=0" in text
    assert "LC_ALL=C.UTF-8" in text
    assert "TZ=UTC" in text
    assert 'USER 65532:65532' in text
    assert 'ENTRYPOINT ["python", "-m", "searise_pipeline.offline_release.cli"]' in text
    assert not ({"curl", "wget", "apt-get"} & set(text.split()))


def test_builder_context_contains_only_reviewed_contract_code_and_lock() -> None:
    lines = IGNORE.read_text(encoding="utf-8").splitlines()

    assert lines[0] == "**"
    assert "!contracts/release/v1/**" in lines
    assert "!src/pipeline/offline_release/**" in lines
    assert "!src/pipeline/requirements-release.lock" in lines
    assert "!src/pipeline/searise_pipeline/**" in lines


def test_every_profile_binds_the_same_container_identity() -> None:
    identities = []
    pipeline_identities = []
    for profile in BuildProfile:
        definition = load_profile_definition(PROFILE_ROOT / f"{profile.value}.json")
        container = definition.tools[0]
        assert container.name == "offline-release-container"
        assert container.version == (
            "python-3.11.15-bookworm@sha256:" + BASE_DIGEST[:12]
        )
        assert container.identity_paths == (
            "src/pipeline/offline_release/Dockerfile",
            "src/pipeline/offline_release/Dockerfile.dockerignore",
        )
        identities.append(container)
        pipeline = definition.tools[1]
        assert pipeline.name == "searise-pipeline"
        assert pipeline.identity_paths[-2:] == (
            "src/pipeline/searise_pipeline/offline_release/schemas/operator-receipt.schema.json",
            "src/pipeline/searise_pipeline/offline_release/schemas/stage-receipt.schema.json",
        )
        pipeline_identities.append(pipeline)

    assert identities[0] == identities[1] == identities[2]
    assert pipeline_identities[0] == pipeline_identities[1] == pipeline_identities[2]
