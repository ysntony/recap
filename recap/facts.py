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


def render_summary_prompt(facts: WorkFacts | AllProjectsFacts, language: str = "english") -> str:
    body = render_all_projects_facts(facts).rstrip() if isinstance(facts, AllProjectsFacts) else render_facts(facts).rstrip()
    language_instruction = "Write the final summary in English."
    sections = "Return sections: Completed, In progress, Risks, Suggested next actions, Suggested commit or PR notes."
    if language == "chinese":
        language_instruction = "Write the final summary in Simplified Chinese."
        sections = "Return sections: 已完成, 进行中, 风险, 建议下一步, 建议提交或 PR 说明."
    return "\n".join(
        [
            "You are Recap, a concise engineering work journal.",
            "Summarize the work facts below. Do not invent facts.",
            language_instruction,
            sections,
            "",
            body,
        ]
    )


def deterministic_summary(facts: WorkFacts | AllProjectsFacts, language: str = "english") -> str:
    if isinstance(facts, AllProjectsFacts):
        return deterministic_all_projects_summary(facts, language=language)
    labels = summary_labels(language)
    lines = [labels["title"], ""]
    lines.append(labels["completed"])
    lines.extend(format_list(facts.completed_turns[-2:] or [labels["no_completed"]]))
    lines.extend(["", labels["in_progress"]])
    if facts.git.is_repo and facts.git.changed_files:
        lines.append(f"- {len(facts.git.changed_files)} changed file(s) are present in git status." if language != "chinese" else f"- git status 中有 {len(facts.git.changed_files)} 个已变更文件。")
    else:
        if facts.git.is_repo:
            lines.append("- Working tree is clean." if language != "chinese" else "- 工作区是干净的。")
        else:
            lines.append("- Git is not initialized for this project." if language != "chinese" else "- 这个项目还没有初始化 Git。")
    for pending in latest_pending_prompts(facts, count=3):
        lines.append(f"- {pending_line(project_label(facts.project), one_line(pending, 140), language)}")
    if facts.threads:
        lines.extend(["", labels["threads"]])
        for thread in facts.threads[:5]:
            title = thread.prompts[-1] if thread.prompts else thread.thread_id
            lines.append(f"- {one_line(title, 180)}")
            if thread.completed_turns:
                lines.append(f"  {labels['outcome']}: {thread.completed_turns[-1]}")
            elif thread.pending_prompts:
                lines.append(f"  {labels['pending']}: {thread.pending_prompts[-1]}")
    lines.extend(["", labels["risks"]])
    risks = translate_attention(facts.attention, language) or facts.tool_failures
    lines.extend(format_list(risks or [labels["no_risk"]]))
    lines.extend(["", labels["next_actions"]])
    if facts.command_kinds.get("test", 0) == 0:
        lines.append("- Run a test command and scan again so Recap can record validation." if language != "chinese" else "- 运行一次测试命令，然后重新 scan，让 Recap 记录验证结果。")
    if facts.git.is_repo and facts.git.changed_files:
        lines.append("- Review changed files and commit once the work is ready." if language != "chinese" else "- 检查已变更文件，确认完成后提交。")
    elif facts.git.is_repo and facts.git.unpushed_commits:
        lines.append("- Push outstanding commits." if language != "chinese" else "- 推送尚未 push 的提交。")
    else:
        lines.append("- Continue with the next product slice: richer file/change extraction or an LLM provider config." if language != "chinese" else "- 继续下一个产品切片：更丰富的文件/变更提取，或 LLM provider 配置。")
    lines.extend(["", labels["commit_notes"]])
    lines.append("- Summarize the commands, prompts, and completed turns from `recap facts`." if language != "chinese" else "- 用 `recap facts` 里的命令、提示和完成记录整理提交或 PR 描述。")
    return "\n".join(lines).rstrip() + "\n"


def deterministic_all_projects_summary(facts: AllProjectsFacts, language: str = "english") -> str:
    labels = summary_labels(language)
    lines = [labels["all_projects_title"], ""]
    lines.append(labels["completed"])
    completed_projects = [project for project in facts.projects if project.completed_turns]
    if not facts.projects:
        lines.append(f"- {labels['no_activity']}")
    elif not completed_projects:
        lines.append(f"- {labels['no_completed']}")
    for project in completed_projects:
        lines.append(f"- {project_label(project.project)}: {one_line(project.completed_turns[-1], 260)}")
    lines.extend(["", labels["in_progress"]])
    in_progress = [
        changed_files_line(project_label(project.project), len(project.git.changed_files), language)
        for project in facts.projects
        if project.git.is_repo and project.git.changed_files
    ]
    in_progress.extend(
        pending_line(project_label(project.project), one_line(pending, 140), language)
        for project in facts.projects
        for pending in latest_pending_prompts(project, count=1)
    )
    lines.extend(format_list(in_progress or [labels["no_changed_files"]]))
    lines.extend(["", labels["risks"]])
    risks = []
    for project in facts.projects:
        risks.extend(f"{project_label(project.project)}: {item}" for item in translate_attention(project.attention[:3], language))
    lines.extend(format_list(risks or [labels["no_risk"]]))
    lines.extend(["", labels["next_actions"]])
    next_actions = []
    for project in facts.projects:
        label = project_label(project.project)
        for pending in latest_pending_prompts(project, count=1):
            next_actions.append(f"Finish the pending `{label}` thread: {one_line(pending, 140)}." if language != "chinese" else f"完成 `{label}` 中待处理的线程：{one_line(pending, 140)}。")
        if project.git.is_repo and project.git.changed_files:
            next_actions.append(f"Review and commit or discard the {len(project.git.changed_files)} changed file(s) in `{label}`." if language != "chinese" else f"检查 `{label}` 中的 {len(project.git.changed_files)} 个已变更文件，并选择提交或丢弃。")
        if "No test command was seen in today's Codex command log." in project.attention:
            next_actions.append(f"Run a validation command in `{label}` and rescan." if language != "chinese" else f"在 `{label}` 中运行验证命令，然后重新 scan。")
    lines.extend(format_list(dedupe(next_actions)[:5] or [labels["review_threads"]]))
    lines.extend(["", labels["commit_notes"]])
    lines.append("- Use each project's thread section as the source for commit or PR summaries." if language != "chinese" else "- 用每个项目的 thread 区块作为提交或 PR 摘要的素材。")
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


def summary_labels(language: str) -> dict[str, str]:
    if language == "chinese":
        return {
            "title": "Recap 摘要",
            "all_projects_title": "全项目 Recap 摘要",
            "completed": "已完成",
            "in_progress": "进行中",
            "threads": "线程",
            "risks": "风险",
            "next_actions": "建议下一步",
            "commit_notes": "建议提交或 PR 说明",
            "outcome": "结果",
            "pending": "待处理",
            "no_activity": "没有检测到项目活动。",
            "no_completed": "这个时间范围内没有检测到已完成的轮次。",
            "no_changed_files": "没有在 Git 仓库中检测到已变更文件。",
            "no_risk": "当前 ledger 中没有明显风险。",
            "review_threads": "先查看活动量最高的项目线程。",
        }
    return {
        "title": "Recap summary",
        "all_projects_title": "All-project recap summary",
        "completed": "Completed",
        "in_progress": "In progress",
        "threads": "Threads",
        "risks": "Risks",
        "next_actions": "Suggested next actions",
        "commit_notes": "Suggested commit or PR notes",
        "outcome": "Outcome",
        "pending": "Pending",
        "no_activity": "No project activity was detected.",
        "no_completed": "No completed turns were detected in this time range.",
        "no_changed_files": "No changed files detected across git repositories.",
        "no_risk": "No obvious risk detected from the current ledger.",
        "review_threads": "Review the highest-activity project threads first.",
    }


def changed_files_line(label: str, count: int, language: str) -> str:
    if language == "chinese":
        return f"{label}: {count} 个已变更文件"
    return f"{label}: {count} changed file(s)"


def pending_line(label: str, prompt: str, language: str) -> str:
    if language == "chinese":
        return f"{label}: 等待处理 `{prompt}`"
    return f"{label}: awaiting response to `{prompt}`"


def translate_attention(items: list[str], language: str) -> list[str]:
    if language != "chinese":
        return items
    translated = []
    for item in items:
        changed = re.fullmatch(r"(\d+) changed file\(s\) are not committed\.", item)
        unpushed = re.fullmatch(r"(\d+) commit\(s\) are not pushed upstream\.", item)
        if changed:
            translated.append(f"{changed.group(1)} 个已变更文件尚未提交。")
        elif unpushed:
            translated.append(f"{unpushed.group(1)} 个提交尚未推送到上游。")
        elif item == "No test command was seen in today's Codex command log.":
            translated.append("今天的 Codex 命令日志中没有看到测试命令。")
        elif item == "Docs changed, but no commit command was seen.":
            translated.append("文档有变更，但没有看到 commit 命令。")
        elif item == "No Codex events found for this project and time range. Run `recap scan` or check the project path.":
            translated.append("这个项目和时间范围内没有找到 Codex 事件。请运行 `recap scan` 或检查项目路径。")
        else:
            translated.append(item)
    return translated


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
