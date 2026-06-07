from __future__ import annotations

import unittest

from recap.facts import classify_commands, dedupe


class FactsTest(unittest.TestCase):
    def test_classify_commands(self) -> None:
        counts = classify_commands(
            [
                "git status --short",
                "python3 -B -m unittest discover",
                "npm run build",
                "git push -u origin main",
                "python3 -m recap today",
            ]
        )

        self.assertEqual(counts["git"], 2)
        self.assertEqual(counts["test"], 1)
        self.assertEqual(counts["build"], 1)
        self.assertEqual(counts["push"], 1)
        self.assertEqual(counts["other"], 1)

    def test_dedupe_preserves_order(self) -> None:
        self.assertEqual(dedupe(["a", "b", "a", "", "c"]), ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
