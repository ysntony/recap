from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from sqlite3 import Row

from .gitinfo import GitStatus


IMPORTANT_KINDS = {"user_message", "assistant_message", "command", "file_edit", "task_complete"}


def render_today(project: Path, since: datetime, rows: list[Row], git: GitStatus) -> str:
    counts = Counter(row["kind"] for row in rows)
    user_prompts = [row for row in rows if row["kind"] == "user_message"]
    commands = [row for row in rows if row["kind"] == "command"]
    edits = [row for row in rows if row["kind"] == "file_edit"]
    summaries = [row for row in rows if row["kind"] == "task_complete"]

    lines = [
        f"Recap for {project}",
        f"Since {since.isoformat()}",
        "",
        "Codex activity",
        f"- Events: {len(rows)}",
        f"- User prompts: {len(user_prompts)}",
        f"- Commands: {len(commands)}",
        f"- File edits: {len(edits)}",
    ]
    if counts:
        kind_summary = ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))
        lines.append(f"- Event mix: {kind_summary}")

    if user_prompts:
        lines.extend(["", "Prompts"])
        for row in user_prompts[-5:]:
            lines.append(f"- {one_line(row['text'])}")

    if commands:
        lines.extend(["", "Commands"])
        for row in commands[-8:]:
            lines.append(f"- {one_line(row['text'])}")

    if summaries:
        lines.extend(["", "Latest completed turn"])
        lines.append(block(summaries[-1]["text"], 900))

    lines.extend(["", render_git(git)])

    attention = attention_items(git, rows)
    if attention:
        lines.extend(["", "Needs attention"])
        lines.extend(f"- {item}" for item in attention)

    return "\n".join(lines).rstrip() + "\n"


def render_status(project: Path, git: GitStatus, stats: dict[str, object]) -> str:
    lines = [
        f"Recap status for {project}",
        "",
        f"Stored sessions: {stats['sessions']}",
        f"Stored events: {stats['events']}",
    ]
    kinds = stats.get("kinds") or {}
    if isinstance(kinds, dict) and kinds:
        lines.append("Event kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    lines.extend(["", render_git(git)])
    return "\n".join(lines).rstrip() + "\n"


def render_timeline(rows: list[Row]) -> str:
    if not rows:
        return "No events found.\n"
    lines: list[str] = []
    for row in rows:
        if row["kind"] not in IMPORTANT_KINDS:
            continue
        ts = row["ts"].replace("T", " ").split("+")[0].replace("Z", "")
        lines.append(f"{ts} [{row['kind']}] {one_line(row['text'], 180)}")
    return "\n".join(lines).rstrip() + "\n"


def render_git(git: GitStatus) -> str:
    if not git.is_repo:
        return "Git\n- Not a git repository yet."
    lines = ["Git"]
    if git.branch:
        lines.append(f"- Branch: {git.branch}")
    if git.head:
        lines.append(f"- HEAD: {git.head}")
    lines.append(f"- Changed files: {len(git.changed_files)}")
    if git.unpushed_commits is not None:
        lines.append(f"- Unpushed commits: {git.unpushed_commits}")
    if git.changed_files:
        for item in git.changed_files[:12]:
            lines.append(f"  {item}")
        if len(git.changed_files) > 12:
            lines.append(f"  ...and {len(git.changed_files) - 12} more")
    return "\n".join(lines)


def attention_items(git: GitStatus, rows: list[Row]) -> list[str]:
    items: list[str] = []
    if not rows:
        items.append("No Codex events found for this project and time range. Run `recap scan` or check the project path.")
    if git.is_repo and git.changed_files:
        items.append(f"{len(git.changed_files)} changed file(s) are not committed.")
    if git.is_repo and git.unpushed_commits:
        items.append(f"{git.unpushed_commits} commit(s) are not pushed upstream.")
    command_text = "\n".join(row["text"] for row in rows if row["kind"] == "command").lower()
    changed_text = "\n".join(git.changed_files).lower()
    if git.is_repo and git.changed_files and "test" not in command_text:
        items.append("No test command was seen in today's Codex command log.")
    if any(word in changed_text for word in ("readme", "docs", "doc")) and "commit" not in command_text:
        items.append("Docs changed, but no commit command was seen.")
    return items


def one_line(value: str, limit: int = 160) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def block(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n...[truncated]"
    return "\n".join(f"  {line}" if line else "" for line in text.splitlines())
