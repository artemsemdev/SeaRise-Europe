"""Tests for metadata-only private candidate isolation."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.repository.check_candidate_isolation import check_candidate_isolation


class CandidateIsolationTests(unittest.TestCase):
    def _repository(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "SeaRise Test"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=root,
            check=True,
        )
        (root / ".github/workflows").mkdir(parents=True)
        (root / "src/web/dist/assets").mkdir(parents=True)
        (root / ".gitignore").write_text("local-data/\n", encoding="utf-8")
        (root / ".github/workflows/ci.yml").write_text("name: CI\n", encoding="utf-8")
        (root / "src/web/dist/index.html").write_text("static\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "test: fixture"], cwd=root, check=True)

    def test_accepts_ignored_private_paths_without_reading_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            private = root / "local-data/phase-1/local-production-run/candidate-v7"
            private.mkdir(parents=True)
            (private / "manifest.json").write_bytes(b"must not be read")

            summary = check_candidate_isolation(root, Path("src/web/dist"))

        self.assertEqual(summary["ignoreProbes"], 2)
        self.assertGreater(summary["trackedPaths"], 0)

    def test_rejects_private_marker_in_tracked_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            path = root / "evidence/candidate-v7.txt"
            path.parent.mkdir()
            path.write_text("metadata\n", encoding="utf-8")
            subprocess.run(["git", "add", "-f", str(path.relative_to(root))], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "test: mutation"], cwd=root, check=True)

            with self.assertRaisesRegex(ValueError, "private candidate path is tracked"):
                check_candidate_isolation(root, Path("src/web/dist"))

    def test_rejects_workflow_and_build_path_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            workflow = root / ".github/workflows/ci.yml"
            workflow.write_text("run: use local-data/phase-1\n", encoding="utf-8")
            subprocess.run(["git", "add", str(workflow.relative_to(root))], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "test: workflow"], cwd=root, check=True)
            with self.assertRaisesRegex(ValueError, "appears in workflow"):
                check_candidate_isolation(root, Path("src/web/dist"))

            workflow.write_text("name: CI\n", encoding="utf-8")
            subprocess.run(["git", "add", str(workflow.relative_to(root))], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "test: restore"], cwd=root, check=True)
            forbidden = root / "src/web/dist/assets/candidate-v7"
            forbidden.mkdir()
            with self.assertRaisesRegex(ValueError, "appears in build path"):
                check_candidate_isolation(root, Path("src/web/dist"))


if __name__ == "__main__":
    unittest.main()
