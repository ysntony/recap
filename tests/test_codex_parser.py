from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from recap.codex import parse_session_file


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class CodexParserTest(unittest.TestCase):
    def test_parse_codex_session_file(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            session_file = tmp_path / "rollout-2026-06-07T14-24-32-019ea0c1-227c-7bd3-8958-39568cd3821c.jsonl"
            write_jsonl(
                session_file,
                [
                    {
                        "timestamp": "2026-06-07T06:24:44.369Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-1",
                            "timestamp": "2026-06-07T06:24:32.380Z",
                            "cwd": str(tmp_path),
                            "originator": "Codex Desktop",
                        },
                    },
                    {
                        "timestamp": "2026-06-07T06:25:00.000Z",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "build the MVP"},
                    },
                    {
                        "timestamp": "2026-06-07T06:25:01.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "arguments": json.dumps({"cmd": "rg --files", "workdir": str(tmp_path)}),
                        },
                    },
                ],
            )

            session, events = parse_session_file(session_file)

            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(session.thread_id, "thread-1")
            self.assertEqual(session.cwd, tmp_path.resolve())
            self.assertEqual([event.kind for event in events], ["user_message", "command"])
            self.assertEqual(events[1].text, "rg --files")


if __name__ == "__main__":
    unittest.main()
