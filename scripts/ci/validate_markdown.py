"""Validate repository-local links in tracked Markdown documentation."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REFERENCE_LINK = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def _without_fenced_code(text: str) -> str:
    lines = []
    fence: Optional[str] = None
    for line in text.splitlines(keepends=True):
        marker = line.lstrip()[:3]
        if marker in {"```", "~~~"}:
            fence = None if fence == marker else marker if fence is None else fence
            lines.append("\n")
        elif fence is None:
            lines.append(line)
        else:
            lines.append("\n")
    return "".join(lines)


def _target(raw: str) -> Optional[str]:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        value = value[1 : value.index(">")]
    else:
        value = value.split(maxsplit=1)[0]
    if not value or value.startswith("#") or SCHEME.match(value):
        return None
    return unquote(value.split("#", 1)[0].split("?", 1)[0])


def validate_markdown_paths(root: Path, files: Sequence[Path]) -> list[str]:
    """Return deterministic errors for missing repository-local link targets."""
    errors = []
    for source in sorted(files):
        text = _without_fenced_code(source.read_text(encoding="utf-8"))
        raw_targets = INLINE_LINK.findall(text) + REFERENCE_LINK.findall(text)
        for raw in raw_targets:
            target = _target(raw)
            if target is None:
                continue
            resolved = (
                root / target.lstrip("/")
                if target.startswith("/")
                else source.parent / target
            )
            if not resolved.exists():
                errors.append(
                    f"{source.relative_to(root).as_posix()}: stale local link {target}"
                )
    return errors


def tracked_markdown(root: Path = ROOT) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [root / line for line in result.stdout.splitlines() if line]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    files = [ROOT / path for path in args.paths] if args.paths else tracked_markdown()
    errors = validate_markdown_paths(ROOT, files)
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print(f"validated {len(files)} tracked Markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
