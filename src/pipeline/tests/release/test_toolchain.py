"""Protect the immutable Python release environment."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from searise_pipeline.release.toolchain import (
    current_python_platform,
    validate_python_toolchain,
)
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import REPO_ROOT, contract


def _lock_path() -> Path:
    profile = contract()["toolchain"]["python"]["profiles"][current_python_platform()]
    return REPO_ROOT / profile["lockPath"]


def test_current_release_environment_matches_every_locked_distribution() -> None:
    evidence = validate_python_toolchain(_lock_path(), contract=contract())

    assert evidence.lock_sha256 == contract()["toolchain"]["python"]["profiles"][
        evidence.platform
    ]["lockSha256"]
    assert evidence.packages == contract()["toolchain"]["python"]["packageVersions"]


def test_python_toolchain_rejects_a_mutated_lock(tmp_path: Path) -> None:
    mutated = tmp_path / _lock_path().name
    mutated.write_bytes(_lock_path().read_bytes() + b"# drift\n")

    with pytest.raises(ScienceContractError, match="release lock differs"):
        validate_python_toolchain(mutated, contract=contract())


def test_python_toolchain_rejects_missing_runtime_import(tmp_path: Path) -> None:
    release = deepcopy(contract())
    original = _lock_path().read_text(encoding="utf-8")
    mutated = tmp_path / _lock_path().name
    mutated.write_text(
        "\n".join(
            line for line in original.splitlines() if not line.startswith("cryptography==")
        )
        + "\n",
        encoding="utf-8",
    )
    profile = release["toolchain"]["python"]["profiles"][current_python_platform()]
    profile["lockSha256"] = hashlib.sha256(mutated.read_bytes()).hexdigest()

    with pytest.raises(ScienceContractError, match="package-version pins"):
        validate_python_toolchain(mutated, contract=release)


def test_python_toolchain_rejects_the_other_platform_lock() -> None:
    profiles = contract()["toolchain"]["python"]["profiles"]
    wrong_profile = next(
        profile for name, profile in profiles.items() if name != current_python_platform()
    )

    with pytest.raises(ScienceContractError, match="release lock differs"):
        validate_python_toolchain(REPO_ROOT / wrong_profile["lockPath"], contract=contract())
