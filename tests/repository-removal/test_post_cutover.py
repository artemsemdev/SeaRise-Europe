"""Current-tree evolution must not rewrite completed removal authority."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.repository import validate_post_cutover as policy


class PostCutoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        project = Path(__file__).resolve().parents[2]
        commit = policy.git(project, "cat-file", "commit", "HEAD")
        self.identity = next(
            line[7:] for line in commit.splitlines() if line.startswith(b"author ")
        )
        self.parent: str | None = None
        self.authority = "scripts/repository/historical.py"
        self.write(self.authority, "# immutable validator\n")
        for stage in policy.STAGES:
            self.write(
                f"{stage}/preapproval.json",
                json.dumps(
                    {
                        "trustRoots": {"validator": self.authority},
                    }
                ),
            )
            self.write(
                f"{stage}/removal-plan.json",
                json.dumps(
                    {
                        "entries": [
                            {
                                "path": "retired-runtime.conf",
                                "after": {"state": "absent"},
                            },
                            {
                                "path": "src/web/scripts/static-repository-gates.mjs",
                                "after": {"state": "present"},
                            },
                        ]
                    }
                ),
            )
            for name in ("owner-decision", "application-receipt"):
                self.write(f"{stage}/{name}.json", "{}\n")
        self.write("src/web/scripts/static-repository-gates.mjs", "// current gate\n")
        self.commit()
        self.anchor = self.git("rev-parse", "HEAD").strip()

    def git(self, *args: str) -> str:
        return policy.git(self.root, *args).decode()

    def write(self, name: str, content: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def commit(self) -> None:
        paths = [
            str(path.relative_to(self.root))
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(self.root).parts
        ]
        self.git("add", "--", *paths)
        tree = self.git("write-tree").strip()
        parent = f"parent {self.parent}\n" if self.parent else ""
        # Reuse project attribution as fixture metadata without configuring or
        # overriding a developer/CI Git identity. No publishing occurs here.
        content = (
            f"tree {tree}\n{parent}".encode()
            + b"author "
            + self.identity
            + b"\ncommitter "
            + self.identity
            + b"\n\ntest: record isolated contract fixture\n"
        )
        result = subprocess.run(
            ["git", "hash-object", "-t", "commit", "-w", "--stdin"],
            cwd=self.root,
            input=content,
            capture_output=True,
            check=True,
        )
        self.parent = result.stdout.decode().strip()
        self.git("update-ref", "HEAD", self.parent)

    def validate(self) -> None:
        policy.validate_current_state(self.root, "HEAD", anchor=self.anchor)

    def test_accepts_retained_application_and_ci_evolution(self) -> None:
        for path in (
            "src/web/scripts/static-repository-gates.mjs",
            "src/web/scripts/check-target-content.mjs",
            "src/web/src/App.tsx",
            ".github/workflows/ci.yml",
            "tests/test-inventory.json",
            "contracts/supply-chain/v2/static-target-profile.json",
        ):
            self.write(path, "reviewed successor\n")
        self.validate()
        self.commit()
        self.validate()

    def test_rejects_uncommitted_receipt_mutation(self) -> None:
        self.write(f"{policy.STAGES[-1]}/application-receipt.json", '{"changed":true}')
        with self.assertRaisesRegex(ValueError, "Working historical authority changed"):
            self.validate()

    def test_rejects_committed_owner_decision_mutation_even_when_checkout_restored(
        self,
    ) -> None:
        path = f"{policy.STAGES[-1]}/owner-decision.json"
        self.write(path, '{"changed":true}')
        self.commit()
        self.write(path, "{}\n")
        with self.assertRaisesRegex(
            ValueError, "Committed historical authority changed"
        ):
            self.validate()

    def test_rejects_changed_historical_validator(self) -> None:
        self.write(self.authority, "# weakened validator\n")
        with self.assertRaisesRegex(ValueError, "Working historical authority changed"):
            self.validate()

    def test_rejects_authority_symlink_and_mode_changes(self) -> None:
        path = self.root / self.authority
        path.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "mode changed"):
            self.validate()
        path.chmod(0o644)
        copy = self.root / "copy.py"
        copy.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.validate()

    def test_rejects_restored_deleted_file_in_worktree_and_commit(self) -> None:
        self.write("retired-runtime.conf", "restored\n")
        with self.assertRaisesRegex(ValueError, "Removed runtime path was restored"):
            self.validate()
        self.commit()
        (self.root / "retired-runtime.conf").unlink()
        with self.assertRaisesRegex(ValueError, "Removed runtime path was restored"):
            self.validate()

    def test_rejects_new_files_and_symlinks_in_retired_runtime_directories(
        self,
    ) -> None:
        for directory in policy.REMOVED_DIRECTORIES:
            with self.subTest(directory=directory):
                path = self.root / directory
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(self.root / "missing")
                with self.assertRaisesRegex(
                    ValueError, "Removed runtime path was restored"
                ):
                    self.validate()
                path.unlink()
                self.write(f"{directory}/new-runtime.txt", "resurrection\n")
                with self.assertRaisesRegex(
                    ValueError, "Removed runtime path was restored"
                ):
                    self.validate()
                (path / "new-runtime.txt").unlink()
                path.rmdir()

    def test_requires_receipt_ancestry(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            policy.validate_current_state(self.root, "HEAD", anchor="0" * 40)

    def test_historical_validation_is_mandatory_and_pinned_to_completed_receipt(
        self,
    ) -> None:
        with (
            patch.object(policy, "validate_current_state") as current,
            patch.object(policy.subprocess, "run") as run,
        ):
            policy.validate_post_cutover(self.root, "current-head")
        current.assert_called_once_with(self.root, "current-head")
        arguments = run.call_args.args[0]
        self.assertEqual(
            arguments[arguments.index("--head-commit") + 1],
            policy.COMPLETED_RECEIPT_COMMIT,
        )
        self.assertEqual(
            arguments[arguments.index("--receipt-commit") + 1],
            policy.COMPLETED_RECEIPT_COMMIT,
        )
        self.assertIn("--verify-owner-comment", arguments)
        self.assertTrue(run.call_args.kwargs["check"])
        with (
            patch.object(
                policy, "validate_current_state", side_effect=ValueError("invalid")
            ),
            patch.object(policy.subprocess, "run") as run,
        ):
            with self.assertRaises(ValueError):
                policy.validate_post_cutover(self.root, "current-head")
            run.assert_not_called()

        with (
            patch.object(policy, "validate_current_state"),
            patch.object(
                policy.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "historical-validator"),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            policy.validate_post_cutover(self.root, "current-head")


if __name__ == "__main__":
    unittest.main()
