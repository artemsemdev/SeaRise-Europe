"""Fail closed when build and release dependencies use mutable references."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTION_SHA = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<reference>[^\s#]+)")
FROM = re.compile(r"^\s*FROM\s+(?:--[^\s]+\s+)*(?P<reference>[^\s#]+)", re.IGNORECASE)
STAGE = re.compile(r"\s+AS\s+(?P<stage>[A-Za-z][A-Za-z0-9_.-]*)", re.IGNORECASE)
IMAGE = re.compile(r"^\s*(?:image|container):\s*(?P<reference>[^\s#]+)")


def _files(repository_root: Path) -> tuple[list[Path], list[Path], list[Path]]:
    workflows = sorted((repository_root / ".github" / "workflows").glob("*.y*ml"))
    dockerfiles = sorted(
        path
        for path in repository_root.rglob("Dockerfile*")
        if path.name != "Dockerfile.dockerignore"
    )
    compose_files = [repository_root / "docker-compose.yml"]
    return workflows, dockerfiles, [path for path in compose_files if path.is_file()]


def _location(repository_root: Path, path: Path, line_number: int) -> str:
    return f"{path.relative_to(repository_root)}:{line_number}"


def _unquote(reference: str) -> str:
    return reference.strip("\"'")


def _validate_workflow(path: Path, repository_root: Path) -> list[str]:
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = USES.match(line)
        if match:
            reference = _unquote(match.group("reference"))
            if reference.startswith("./"):
                continue
            if reference.startswith("docker://"):
                image = reference.removeprefix("docker://")
                if not IMAGE_DIGEST.search(image):
                    errors.append(
                        f"{_location(repository_root, path, line_number)}: "
                        f"container action must use an image digest: {reference}"
                    )
                continue
            if "@" not in reference or not ACTION_SHA.fullmatch(reference.rsplit("@", 1)[1]):
                errors.append(
                    f"{_location(repository_root, path, line_number)}: "
                    f"GitHub Action must use a full commit SHA: {reference}"
                )
            continue

        image_match = IMAGE.match(line)
        if image_match:
            reference = _unquote(image_match.group("reference"))
            if not IMAGE_DIGEST.search(reference):
                errors.append(
                    f"{_location(repository_root, path, line_number)}: "
                    f"container image must use a sha256 digest: {reference}"
                )
    return errors


def _validate_dockerfile(path: Path, repository_root: Path) -> list[str]:
    errors: list[str] = []
    stages: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = FROM.match(line)
        if not match:
            continue
        reference = _unquote(match.group("reference"))
        if reference not in stages and not IMAGE_DIGEST.search(reference):
            errors.append(
                f"{_location(repository_root, path, line_number)}: "
                f"Docker base image must use a sha256 digest: {reference}"
            )
        stage_match = STAGE.search(line)
        if stage_match:
            stages.add(stage_match.group("stage"))
    return errors


def _validate_compose(path: Path, repository_root: Path) -> list[str]:
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = IMAGE.match(line)
        if not match:
            continue
        reference = _unquote(match.group("reference"))
        if not IMAGE_DIGEST.search(reference):
            errors.append(
                f"{_location(repository_root, path, line_number)}: "
                f"container image must use a sha256 digest: {reference}"
            )
    return errors


def validate_repository(repository_root: Path = ROOT) -> list[str]:
    """Return every mutable in-scope action or image reference."""
    workflows, dockerfiles, compose_files = _files(repository_root)
    errors = [
        error
        for workflow in workflows
        for error in _validate_workflow(workflow, repository_root)
    ]
    errors.extend(
        error
        for dockerfile in dockerfiles
        for error in _validate_dockerfile(dockerfile, repository_root)
    )
    errors.extend(
        error
        for compose_file in compose_files
        for error in _validate_compose(compose_file, repository_root)
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args()

    errors = validate_repository(args.repository_root.resolve())
    if errors:
        print("immutable dependency validation failed:")
        print("\n".join(errors))
        return 1
    print("validated immutable GitHub Actions and container image dependencies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
