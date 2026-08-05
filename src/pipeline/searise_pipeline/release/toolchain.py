"""Fail-closed validation for the immutable Python release environment."""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from searise_pipeline.science.contracts import ScienceContractError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PythonToolchainEvidence:
    """Observed interpreter and native-library identities bound to the lock."""

    platform: str
    python_version: str
    lock_path: str
    lock_sha256: str
    packages: Mapping[str, str]
    gdal_version: str
    rasterio_proj_version: str
    pyproj_proj_version: str


_LOCK_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^ ]+) --hash=sha256:[0-9a-f]{64}$"
)


def current_python_platform() -> str:
    """Return the contract profile key for the running interpreter."""
    return (
        f"{platform.system().lower().replace('darwin', 'macos')}-"
        f"{platform.machine().lower()}-cp{sys.version_info.major}{sys.version_info.minor}"
    )


def validate_python_toolchain(
    lock_path: Path,
    *,
    contract: Mapping[str, Any],
) -> PythonToolchainEvidence:
    """Require the exact lock, package versions, interpreter, GDAL, and PROJ."""
    pin = contract["toolchain"]["python"]
    observed_python = ".".join(map(str, sys.version_info[:3]))
    observed_platform = current_python_platform()
    profile = pin["profiles"].get(observed_platform)
    if profile is None or observed_python != profile["pythonVersion"]:
        raise ScienceContractError("Python interpreter differs from the release platform")
    if (
        not lock_path.is_file()
        or lock_path.as_posix().split("/")[-1] != Path(profile["lockPath"]).name
        or _sha256(lock_path) != profile["lockSha256"]
    ):
        raise ScienceContractError("Python release lock differs from the platform profile")
    locked: dict[str, str] = {}
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or line.startswith("  "):
            continue
        match = _LOCK_LINE.fullmatch(line)
        if match is None:
            raise ScienceContractError("Python release lock contains an unpinned entry")
        locked[match.group("name")] = match.group("version")
    if locked != pin["packageVersions"]:
        raise ScienceContractError("Python release lock differs from package-version pins")
    packages: dict[str, str] = {}
    for distribution, expected in locked.items():
        try:
            observed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ScienceContractError(
                f"Pinned Python package is absent: {distribution}"
            ) from exc
        if observed != expected:
            raise ScienceContractError(
                f"Python package {distribution} differs from the release contract"
            )
        packages[distribution] = observed

    import pyproj
    import rasterio

    gdal_version = str(rasterio.__gdal_version__)
    rasterio_proj_version = str(rasterio.__proj_version__)
    pyproj_proj_version = str(pyproj.proj_version_str)
    if (
        gdal_version != profile["gdal"]
        or rasterio_proj_version != profile["rasterioProj"]
        or pyproj_proj_version != profile["pyprojProj"]
    ):
        raise ScienceContractError("GDAL or PROJ runtime differs from the release contract")
    return PythonToolchainEvidence(
        platform=observed_platform,
        python_version=observed_python,
        lock_path=profile["lockPath"],
        lock_sha256=profile["lockSha256"],
        packages=packages,
        gdal_version=gdal_version,
        rasterio_proj_version=rasterio_proj_version,
        pyproj_proj_version=pyproj_proj_version,
    )
