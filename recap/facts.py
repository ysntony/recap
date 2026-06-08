from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from sqlite3 import Row

from .gitinfo import GitStatus
from .report import attention_items, one_line


COMMAND_PATTERNS = {
    "git": re.compile(r"(^|\s)git(\s|$)"),
    "test": re.compile(r"\b(pytest|unittest|npm test|cargo test|go test|pnpm test|yarn test)\b"),
    "build": re.compile(r"\b(npm run build|pnpm build|yarn build|cargo build|go build|make)\b"),
    "push": re.compile(r"\bgit\s+push\b"),
    "commit": re.compile(r"\bgit\s+commit\b"),
}
FILE_RE = re.compile(r"(?<![\w./-])(?:[\w.-]+/)*[\w.-]+\.(?:py|ts|tsx|js|jsx|json|toml|md|sqlite|yaml|yml|txt)")


@dataclass(frozen=True)
class ThreadFacts:
    thread_id: str
    event_count: int
    prompts: list[str]
    pending_prompts: list[str]
    commands: list[str]
    completed_turns: list[str]
    tool_failures: list[str]
    started_at: str | None
    updated_at: str | None


@dataclass(frozen=True)
class WorkFacts:
    project: Path
    since: datetime
    event_count: int
    event_kinds: dict[str, int]
    thread_count: int
    prompts: list[str]
    commands: list[str]
    command_kinds: dict[str, int]
    files_mentioned: list[str]
    completed_turns: list[str]
    tool_failures: list[str]
    threads: list[ThreadFacts]
    git: GitStatus
    attention: list[str]


@dataclass(frozen=True)
class AllProjectsFacts:
    since: datetime
    projects: list[WorkFacts]


def build_work_facts(project: Path, since: datetime, rows: list[Row], git: GitStatus) -> WorkFacts:
    event_kinds = Counter(row["kind"] for row in rows)
    thread_count = len({row["thread_id"] for row in rows if row["thread_id"]})
    prompts = dedupe(clean_prompt(row["text"], 260) for row in rows if row["kind"] == "user_message" and not is_internal_prompt(row["text"]))
    commands = [row["text"] for row in rows if row["kind"] == "command"]
    files = sorted(extract_files(rows, git))
    failures = extract_failures(rows)
    threads = build_thread_facts(rows)
    completed_turns = [
        completed
        for thread in sorted(threads, key=lambda item: item.updated_at or "")
        for completed in thread.completed_turns
    ]
    return WorkFacts(
        project=project,
        since=since,
        event_count=len(rows),
        event_kinds=dict(sorted(event_kinds.items())),
        thread_count=thread_count,
        prompts=prompts[-8:],
        commands=commands[-20:],
        command_kinds=classify_commands(commands),
        files_mentioned=files[:80],
        completed_turns=completed_turns[-5:],
        tool_failures=failures[-10:],
        threads=threads,
        git=git,
        attention=attention_items(git, rows),
    )


def build_all_projects_facts(since: datetime, rows: list[Row]) -> AllProjectsFacts:
    by_project: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        project_path = row["project_path"]
        if project_path:
            by_project[project_path].append(row)

    projects: list[WorkFacts] = []
    for project_path, project_rows in sorted(by_project.items()):
        project = Path(project_path)
        projects.append(build_work_facts(project, since, project_rows, git_for_project(project)))
    projects.sort(key=lambda facts: max((row["ts"] for row in by_project[str(facts.project)]), default=""), reverse=True)
    return AllProjectsFacts(since=since, projects=projects)


def render_facts(facts: WorkFacts) -> str:
    lines = [
        f"Work facts for {facts.project}",
        f"Since {facts.since.isoformat()}",
        "",
        "Activity",
        f"- Events: {facts.event_count}",
        f"- Threads: {facts.thread_count}",
        "- Event kinds: " + format_counts(facts.event_kinds),
        "- Command kinds: " + format_counts(facts.command_kinds),
    ]
    lines.extend(["", "Prompts"])
    lines.extend(format_list(facts.prompts))
    lines.extend(["", "Recent commands"])
    lines.extend(format_list(facts.commands[-10:]))
    lines.extend(["", "Files mentioned"])
    lines.extend(format_list(facts.files_mentioned[:20]))
    if facts.completed_turns:
        lines.extend(["", "Completed turns"])
        lines.extend(format_list(facts.completed_turns))
    if facts.threads:
        lines.extend(["", "Threads"])
        for thread in facts.threads[:8]:
            lines.extend(render_thread_block(thread))
    if facts.tool_failures:
        lines.extend(["", "Tool failures"])
        lines.extend(format_list(facts.tool_failures))
    lines.extend(["", "Git"])
    if facts.git.is_repo:
        lines.append(f"- Branch: {facts.git.branch or '(detached)'}")
        lines.append(f"- HEAD: {facts.git.head or '(unknown)'}")
        lines.append(f"- Changed files: {len(facts.git.changed_files)}")
        lines.append(f"- Unpushed commits: {facts.git.unpushed_commits if facts.git.unpushed_commits is not None else 'unknown'}")
    else:
        lines.append("- Not a git repository")
    if facts.attention:
        lines.extend(["", "Needs attention"])
        lines.extend(format_list(facts.attention))
    return "\n".join(lines).rstrip() + "\n"


def render_all_projects_facts(facts: AllProjectsFacts) -> str:
    lines = [
        "All-project work facts",
        f"Since {facts.since.isoformat()}",
        f"Projects: {len(facts.projects)}",
    ]
    for project in facts.projects:
        lines.extend(
            [
                "",
                f"Project: {project.project}",
                f"- Events: {project.event_count}",
                f"- Threads: {project.thread_count}",
                "- Event kinds: " + format_counts(project.event_kinds),
                "- Command kinds: " + format_counts(project.command_kinds),
            ]
        )
        if project.prompts:
            lines.append("- Prompts: " + " | ".join(project.prompts[-3:]))
        if project.completed_turns:
            lines.append("- Latest completed: " + project.completed_turns[-1])
        pending = latest_pending_prompt(project)
        if pending:
            lines.append("- Pending: " + pending)
        if project.git.is_repo:
            lines.append(
                f"- Git: {project.git.branch or '(detached)'} @ {project.git.head or '(unknown)'}, "
                f"{len(project.git.changed_files)} changed, "
                f"{project.git.unpushed_commits if project.git.unpushed_commits is not None else 'unknown'} unpushed"
            )
        if project.attention:
            lines.append("- Attention: " + " | ".join(project.attention[:3]))
        if project.threads:
            lines.append("- Threads:")
            for thread in project.threads[:4]:
                title = thread.prompts[-1] if thread.prompts else thread.thread_id
                lines.append(f"  - {one_line(title, 180)}")
                if thread.completed_turns:
                    lines.append(f"    Outcome: {thread.completed_turns[-1]}")
                elif thread.pending_prompts:
                    lines.append(f"    Pending: {thread.pending_prompts[-1]}")
    return "\n".join(lines).rstrip() + "\n"


def render_summary_prompt(facts: WorkFacts | AllProjectsFacts) -> str:
    body = render_all_projects_facts(facts).rstrip() if isinstance(facts, AllProjectsFacts) else render_facts(facts).rstrip()
    return "\n".join(
        [
            "You are Recap, a concise engineering work journal.",
            "Summarize the work facts below. Do not invent facts.",
            "Return sections: Completed, In progress, Risks, Suggested next actions, Suggested commit or PR notes.",
            "",
            body,
        ]
    )


def deterministic_summary(facts: WorkFacts | AllProjectsFacts) -> str:
    if isinstance(facts, AllProjectsFacts):
        return deterministic_all_projects_summary(facts)
    completed = facts.completed_turns[-2:] or facts.prompts[-2:]
    lines = ["Recap summary", ""]
    lines.append("Completed")
    lines.extend(format_list(completed or ["No completed turn was detected in this time range."]))
    lines.extend(["", "In progress"])
    if facts.git.is_repo and facts.git.changed_files:
        lines.append(f"- {len(facts.git.changed_files)} changed file(s) are present in git status.")
    else:
        lines.append("- Working tree is clean." if facts.git.is_repo else "- Git is not initialized for this project.")
    if facts.threads:
        lines.extend(["", "Threads"])
        for thread in facts.threads[:5]:
            title = thread.prompts[-1] if thread.prompts else thread.thread_id
            lines.append(f"- {one_line(title, 180)}")
            if thread.completed_turns:
                lines.append(f"  Outcome: {thread.completed_turns[-1]}")
            elif thread.pending_prompts:
                lines.append(f"  Pending: {thread.pending_prompts[-1]}")
    lines.extend(["", "Risks"])
    risks = facts.attention or facts.tool_failures
    lines.extend(format_list(risks or ["No obvious risk detected from the current ledger."]))
    lines.extend(["", "Suggested next actions"])
    if facts.command_kinds.get("test", 0) == 0:
        lines.append("- Run a test command and scan again so Recap can record validation.")
    if facts.git.is_repo and facts.git.changed_files:
        lines.append("- Review changed files and commit once the work is ready.")
    elif facts.git.is_repo and facts.git.unpushed_commits:
        lines.append("- Push outstanding commits.")
    else:
        lines.append("- Continue with the next product slice: richer file/change extraction or an LLM provider config.")
    lines.extend(["", "Suggested commit or PR notes"])
    lines.append("- Summarize the commands, prompts, and completed turns from `recap facts`.")
    return "\n".join(lines).rstrip() + "\n"


def deterministic_all_projects_summary(facts: AllProjectsFacts) -> str:
    lines = ["All-project recap summary", ""]
    lines.append("Completed")
    completed_projects = [project for project in facts.projects if project.completed_turns]
    if not facts.projects:
        lines.append("- No project activity was detected.")
    elif not completed_projects:
        lines.append("- No completed turns were detected in this time range.")
    for project in completed_projects:
        lines.append(f"- {project_label(project.project)}: {one_line(project.completed_turns[-1], 260)}")
    lines.extend(["", "In progress"])
    in_progress = [
        f"{project_label(project.project)}: {len(project.git.changed_files)} changed file(s)"
        for project in facts.projects
        if project.git.is_repo and project.git.changed_files
    ]
    in_progress.extend(
        f"{project_label(project.project)}: awaiting response to `{one_line(pending, 140)}`"
        for project in facts.projects
        for pending in latest_pending_prompts(project, count=1)
    )
    lines.extend(format_list(in_progress or ["No changed files detected across git repositories."]))
    lines.extend(["", "Risks"])
    risks = []
    for project in facts.projects:
        risks.extend(f"{project_label(project.project)}: {item}" for item in project.attention[:3])
    lines.extend(format_list(risks or ["No obvious risk detected from the current ledger."]))
    lines.extend(["", "Suggested next actions"])
    next_actions = []
    for project in facts.projects:
        label = project_label(project.project)
        for pending in latest_pending_prompts(project, count=1):
            next_actions.append(f"Finish the pending `{label}` thread: {one_line(pending, 140)}.")
        if project.git.is_repo and project.git.changed_files:
            next_actions.append(f"Review and commit or discard the {len(project.git.changed_files)} changed file(s) in `{label}`.")
        if "No test command was seen in today's Codex command log." in project.attention:
            next_actions.append(f"Run a validation command in `{label}` and rescan.")
    lines.extend(format_list(dedupe(next_actions)[:5] or ["Review the highest-activity project threads first."]))
    lines.extend(["", "Suggested commit or PR notes"])
    lines.append("- Use each project's thread section as the source for commit or PR summaries.")
    return "\n".join(lines).rstrip() + "\n"


def build_thread_facts(rows: list[Row]) -> list[ThreadFacts]:
    by_thread: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        by_thread[row["thread_id"]].append(row)

    threads: list[ThreadFacts] = []
    for thread_id, thread_rows in by_thread.items():
        prompts = dedupe(
            clean_prompt(row["text"], 220)
            for row in thread_rows
            if row["kind"] == "user_message" and not is_internal_prompt(row["text"])
        )
        commands = [row["text"] for row in thread_rows if row["kind"] == "command"]
        latest_user_ts = max((row["ts"] for row in thread_rows if row["kind"] == "user_message" and not is_internal_prompt(row["text"])), default=None)
        latest_completed_ts = max((row["ts"] for row in thread_rows if row["kind"] == "task_complete" and not looks_like_json(row["text"])), default=None)
        completed = [
            one_line(row["text"], 420)
            for row in thread_rows
            if row["kind"] == "task_complete"
            and not looks_like_json(row["text"])
            and (latest_user_ts is None or row["ts"] >= latest_user_ts)
        ]
        pending_prompts = prompts[-1:] if latest_user_ts and (latest_completed_ts is None or latest_user_ts > latest_completed_ts) else []
        failures = extract_failures(thread_rows)
        timestamps = [row["ts"] for row in thread_rows]
        threads.append(
            ThreadFacts(
                thread_id=thread_id,
                event_count=len(thread_rows),
                prompts=prompts[-5:],
                pending_prompts=pending_prompts,
                commands=commands[-8:],
                completed_turns=completed[-3:],
                tool_failures=failures[-5:],
                started_at=min(timestamps) if timestamps else None,
                updated_at=max(timestamps) if timestamps else None,
            )
        )
    threads.sort(key=lambda thread: thread.updated_at or "", reverse=True)
    return threads


def render_thread_block(thread: ThreadFacts) -> list[str]:
    title = thread.prompts[-1] if thread.prompts else thread.thread_id
    lines = [f"- {one_line(title, 180)}"]
    lines.append(f"  Thread: {thread.thread_id}")
    lines.append(f"  Events: {thread.event_count}")
    if thread.commands:
        lines.append("  Recent commands: " + " | ".join(one_line(command, 80) for command in thread.commands[-4:]))
    if thread.completed_turns:
        lines.append("  Outcome: " + thread.completed_turns[-1])
    elif thread.pending_prompts:
        lines.append("  Pending: " + thread.pending_prompts[-1])
    if thread.tool_failures:
        lines.append("  Failures: " + " | ".join(thread.tool_failures[:2]))
    return lines


def classify_commands(commands: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for command in commands:
        lowered = command.lower()
        matched = False
        for name, pattern in COMMAND_PATTERNS.items():
            if pattern.search(lowered):
                counts[name] += 1
                matched = True
        if not matched:
            counts["other"] += 1
    return dict(sorted(counts.items()))


def git_for_project(project: Path) -> GitStatus:
    from .gitinfo import inspect_git

    return inspect_git(project)


def extract_files(rows: list[Row], git: GitStatus) -> set[str]:
    files = {item[3:].strip() for item in git.changed_files if len(item) > 3}
    for row in rows:
        if row["kind"] not in {"command", "file_edit"}:
            continue
        files.update(FILE_RE.findall(row["text"]))
    return {value for value in files if not value.startswith(".recap/")}


def extract_failures(rows: list[Row]) -> list[str]:
    failures: list[str] = []
    for row in rows:
        if row["kind"] != "tool_output":
            continue
        text = row["text"]
        lowered = text.lower()
        if "exit code 0" in lowered:
            continue
        if any(marker in lowered for marker in ("exit code 1", "exit code 128", "fatal:", "permissionerror", "permission denied", "error:")):
            failures.append(one_line(text, 260))
    return dedupe(failures)


def dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def clean_prompt(text: str, limit: int) -> str:
    marker = "## My request for Codex:"
    if marker in text:
        text = text.split(marker, 1)[1]
    return one_line(text, limit)


def latest_pending_prompt(facts: WorkFacts) -> str | None:
    prompts = latest_pending_prompts(facts, count=1)
    return prompts[0] if prompts else None


def latest_pending_prompts(facts: WorkFacts, count: int) -> list[str]:
    pending: list[str] = []
    for thread in facts.threads:
        pending.extend(reversed(thread.pending_prompts))
    return pending[:count]


def project_label(project: Path) -> str:
    parts = project.parts
    if "work-projects" in parts:
        index = parts.index("work-projects")
        return "/".join(parts[index + 1 :]) or project.name
    if "Codex" in parts:
        index = parts.index("Codex")
        return "/".join(parts[index:]) or project.name
    return project.name or str(project)


def is_internal_prompt(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(
        (
            "The following is the Codex agent history whose request action you are assessing",
            "The following is the Codex agent history added since your last approval assessment",
        )
    )


def looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("{") and stripped.endswith("}")


def format_counts(values: dict[str, int]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(values.items()))


def format_list(values: list[str]) -> list[str]:
    if not values:
        return ["- none"]
    return [f"- {value}" for value in values]


def facts_to_json(facts: WorkFacts) -> str:
    payload = {
        "project": str(facts.project),
        "since": facts.since.isoformat(),
        "event_count": facts.event_count,
        "event_kinds": facts.event_kinds,
        "thread_count": facts.thread_count,
        "prompts": facts.prompts,
        "commands": facts.commands,
        "command_kinds": facts.command_kinds,
        "files_mentioned": facts.files_mentioned,
        "completed_turns": facts.completed_turns,
        "tool_failures": facts.tool_failures,
        "threads": [
            {
                "thread_id": thread.thread_id,
                "event_count": thread.event_count,
                "prompts": thread.prompts,
                "pending_prompts": thread.pending_prompts,
                "commands": thread.commands,
                "completed_turns": thread.completed_turns,
                "tool_failures": thread.tool_failures,
                "started_at": thread.started_at,
                "updated_at": thread.updated_at,
            }
            for thread in facts.threads
        ],
        "git": {
            "is_repo": facts.git.is_repo,
            "branch": facts.git.branch,
            "head": facts.git.head,
            "changed_files": list(facts.git.changed_files),
            "unpushed_commits": facts.git.unpushed_commits,
        },
        "attention": facts.attention,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def all_projects_facts_to_json(facts: AllProjectsFacts) -> str:
    payload = {
        "since": facts.since.isoformat(),
        "projects": [json.loads(facts_to_json(project)) for project in facts.projects],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
