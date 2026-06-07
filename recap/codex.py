from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import CodexSession, RecapEvent, parse_dt, utc_now


def default_codex_home() -> Path:
    return Path.home() / ".codex"


def discover_session_files(codex_home: Path) -> list[Path]:
    roots = [codex_home / "sessions", codex_home / "archived_sessions"]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(sorted(root.rglob("*.jsonl")))
    return files


def parse_session_file(path: Path) -> tuple[CodexSession | None, list[RecapEvent]]:
    session: CodexSession | None = None
    events: list[RecapEvent] = []
    thread_id = thread_id_from_path(path)
    project_path: Path | None = None
    started_at = None
    last_seen = None

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = parse_dt(record.get("timestamp")) or utc_now()
            last_seen = ts
            record_type = record.get("type")
            payload = record.get("payload") or {}

            if record_type == "session_meta":
                meta = payload
                thread_id = str(meta.get("id") or thread_id)
                cwd_value = meta.get("cwd")
                project_path = Path(cwd_value).expanduser().resolve() if cwd_value else None
                started_at = parse_dt(meta.get("timestamp")) or ts
                session = CodexSession(
                    thread_id=thread_id,
                    path=path,
                    cwd=project_path,
                    started_at=started_at,
                    updated_at=ts,
                    metadata={
                        "originator": meta.get("originator"),
                        "cli_version": meta.get("cli_version"),
                        "source": meta.get("source"),
                        "model_provider": meta.get("model_provider"),
                    },
                )
                continue

            for kind, text, metadata in events_from_record(record_type, payload):
                if not text:
                    continue
                events.append(
                    RecapEvent(
                        event_id=stable_event_id(path, line_no, kind, text),
                        thread_id=thread_id,
                        source="codex",
                        project_path=project_path,
                        timestamp=ts,
                        kind=kind,
                        text=clean_text(text),
                        metadata={
                            "line": line_no,
                            "rollout_path": str(path),
                            **metadata,
                        },
                    )
                )

    if session is None and events:
        session = CodexSession(
            thread_id=thread_id,
            path=path,
            cwd=project_path,
            started_at=started_at or events[0].timestamp,
            updated_at=last_seen or events[-1].timestamp,
        )
    elif session is not None:
        session = CodexSession(
            thread_id=session.thread_id,
            path=session.path,
            cwd=session.cwd,
            started_at=session.started_at,
            updated_at=last_seen or session.updated_at,
            title=session.title,
            metadata=session.metadata,
        )

    return session, events


def events_from_record(record_type: str, payload: dict[str, Any]) -> Iterable[tuple[str, str, dict[str, Any]]]:
    if record_type == "event_msg":
        payload_type = payload.get("type")
        if payload_type == "user_message":
            yield "user_message", str(payload.get("message") or ""), {"phase": "conversation"}
        elif payload_type == "agent_message":
            phase = payload.get("phase") or "message"
            kind = "assistant_message" if phase != "commentary" else "assistant_update"
            yield kind, str(payload.get("message") or ""), {"phase": phase}
        elif payload_type == "task_complete":
            yield "task_complete", str(payload.get("last_agent_message") or ""), {
                "turn_id": payload.get("turn_id"),
                "duration_ms": payload.get("duration_ms"),
            }
        return

    if record_type != "response_item":
        return

    item_type = payload.get("type")
    if item_type == "function_call":
        name = str(payload.get("name") or "tool")
        args_text = str(payload.get("arguments") or "")
        args = parse_json_object(args_text)
        if name == "exec_command" and isinstance(args, dict):
            text = str(args.get("cmd") or "")
            yield "command", text, {"tool": name, "arguments": args}
        elif name == "apply_patch":
            yield "file_edit", "apply_patch", {"tool": name, "arguments": args_text[:4000]}
        else:
            yield "tool_call", name, {"tool": name, "arguments": args if args is not None else args_text[:4000]}
    elif item_type == "function_call_output":
        output = str(payload.get("output") or "")
        yield "tool_output", output, {"call_id": payload.get("call_id")}
    elif item_type == "message":
        # Codex also writes conversation text as event_msg records. Skipping
        # response_item messages keeps the event ledger from double-counting.
        return


def message_text(content: list[Any]) -> str:
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"input_text", "output_text"}:
            parts.append(str(item.get("text") or ""))
    return "\n".join(part for part in parts if part)


def parse_json_object(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def thread_id_from_path(path: Path) -> str:
    stem = path.stem
    parts = stem.split("-")
    if len(parts) >= 7:
        return "-".join(parts[-5:])
    return stem


def stable_event_id(path: Path, line_no: int, kind: str, text: str) -> str:
    raw = f"{path}:{line_no}:{kind}:{text[:256]}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def clean_text(text: str, limit: int = 8000) -> str:
    compact = "\n".join(line.rstrip() for line in text.strip().splitlines())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "\n...[truncated]"
