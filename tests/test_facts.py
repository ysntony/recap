from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from recap.facts import build_all_projects_facts, build_work_facts, classify_commands, dedupe
from recap.gitinfo import GitStatus
from recap.llm import LLMError, summarize_with_openrouter


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

    def test_openrouter_requires_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(LLMError):
                summarize_with_openrouter("hello")

    def test_thread_grouping(self) -> None:
        rows = [
            row("thread-a", "/tmp/project-a", "2026-06-08T01:00:00+00:00", "user_message", "build it"),
            row("thread-a", "/tmp/project-a", "2026-06-08T01:01:00+00:00", "command", "python3 -m unittest discover"),
            row("thread-b", "/tmp/project-a", "2026-06-08T02:00:00+00:00", "user_message", "ship it"),
        ]

        facts = build_work_facts(
            Path("/tmp/project-a"),
            datetime(2026, 6, 8, tzinfo=timezone.utc),
            rows,
            GitStatus(is_repo=False),
        )

        self.assertEqual(facts.thread_count, 2)
        self.assertEqual([thread.thread_id for thread in facts.threads], ["thread-b", "thread-a"])
        self.assertEqual(facts.threads[1].commands, ["python3 -m unittest discover"])

    def test_all_project_grouping(self) -> None:
        rows = [
            row("thread-a", "/tmp/project-a", "2026-06-08T01:00:00+00:00", "user_message", "build it"),
            row("thread-b", "/tmp/project-b", "2026-06-08T02:00:00+00:00", "user_message", "document it"),
        ]

        facts = build_all_projects_facts(datetime(2026, 6, 8, tzinfo=timezone.utc), rows)

        self.assertEqual(len(facts.projects), 2)
        self.assertEqual({str(project.project) for project in facts.projects}, {"/tmp/project-a", "/tmp/project-b"})

def row(thread_id: str, project: str, ts: str, kind: str, text: str) -> dict[str, str]:
    return {
        "thread_id": thread_id,
        "project_path": project,
        "ts": ts,
        "kind": kind,
        "text": text,
    }


if __name__ == "__main__":
    unittest.main()
