from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.ci.validate_markdown import validate_markdown_paths


class MarkdownValidationTests(unittest.TestCase):
    def test_accepts_existing_relative_file_and_anchor_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "target.md").write_text("# Target\n", encoding="utf-8")
            source = docs / "source.md"
            source.write_text(
                "[target](target.md#target) and [external](https://example.com)\n",
                encoding="utf-8",
            )

            self.assertEqual(validate_markdown_paths(root, [source]), [])

    def test_rejects_stale_local_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "README.md"
            source.write_text("[removed](docs/removed.md)\n", encoding="utf-8")

            errors = validate_markdown_paths(root, [source])

            self.assertEqual(len(errors), 1)
            self.assertIn("docs/removed.md", errors[0])


if __name__ == "__main__":
    unittest.main()
