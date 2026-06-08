from __future__ import annotations

import argparse
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from .codex import default_codex_home, discover_session_files, parse_session_file
from .facts import (
    all_projects_facts_to_json,
    build_all_projects_facts,
    build_work_facts,
    deterministic_summary,
    facts_to_json,
    render_all_projects_facts,
    render_facts,
    render_summary_prompt,
)
from .gitinfo import inspect_git
from .llm import LLMError, summarize_with_openai, summarize_with_openrouter
from .report import render_status, render_timeline, render_today
from .store import EventStore, default_db_path, default_global_db_path


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    all_projects = getattr(args, "all_projects", False)
    db_path = Path(args.db).expanduser().resolve() if args.db else default_db_path_for(project, all_projects)

    if args.command == "scan":
        return cmd_scan(args, project, db_path)
    if args.command == "today":
        if not args.no_scan:
            cmd_scan(args, project, db_path, quiet=True)
        return cmd_today(args, project, db_path)
    if args.command == "facts":
        if not args.no_scan:
            cmd_scan(args, project, db_path, quiet=True)
        return cmd_facts(args, project, db_path)
    if args.command == "summarize":
        if not args.no_scan:
            cmd_scan(args, project, db_path, quiet=True)
        return cmd_summarize(args, project, db_path)
    if args.command == "status":
        return cmd_status(args, project, db_path)
    if args.command == "timeline":
        return cmd_timeline(args, project, db_path)

    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recap", description="Recap Codex work for a local project.")
    parser.add_argument("--project", default=".", help="Project path to recap. Defaults to current directory.")
    parser.add_argument("--db", default=None, help="SQLite database path. Defaults to PROJECT/.recap/recap.sqlite.")

    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Ingest Codex JSONL sessions into the local Recap database.")
    scan.add_argument("--codex-home", default=str(default_codex_home()), help="Codex home directory.")
    scan.add_argument("--rebuild", action="store_true", help="Clear existing events for this project before scanning.")
    scan.add_argument("--all-projects", action="store_true", help="Scan all Codex projects into the global Recap database.")

    today = sub.add_parser("today", help="Show today's Codex and git recap.")
    today.add_argument("--codex-home", default=str(default_codex_home()), help="Codex home directory.")
    today.add_argument("--since", default=None, help="Start date/time, e.g. 2026-06-07 or 2026-06-07T09:00.")
    today.add_argument("--no-scan", action="store_true", help="Use existing database contents without scanning first.")
    today.add_argument("--all-projects", action="store_true", help="Show all projects from the global Recap database.")
    today.set_defaults(rebuild=False)

    facts = sub.add_parser("facts", help="Show compact work facts for summarization.")
    facts.add_argument("--codex-home", default=str(default_codex_home()), help="Codex home directory.")
    facts.add_argument("--since", default=None, help="Start date/time, e.g. 2026-06-07 or 2026-06-07T09:00.")
    facts.add_argument("--no-scan", action="store_true", help="Use existing database contents without scanning first.")
    facts.add_argument("--json", action="store_true", help="Print facts as JSON.")
    facts.add_argument("--all-projects", action="store_true", help="Show all projects from the global Recap database.")
    facts.set_defaults(rebuild=False)

    summarize = sub.add_parser("summarize", help="Summarize compact work facts, optionally using an LLM provider.")
    summarize.add_argument("--codex-home", default=str(default_codex_home()), help="Codex home directory.")
    summarize.add_argument("--since", default=None, help="Start date/time, e.g. 2026-06-07 or 2026-06-07T09:00.")
    summarize.add_argument("--no-scan", action="store_true", help="Use existing database contents without scanning first.")
    summarize.add_argument("--all-projects", action="store_true", help="Summarize all projects from the global Recap database.")
    summarize.add_argument("--prompt", action="store_true", help="Print the LLM prompt instead of summarizing.")
    summarize.add_argument("--llm", choices=["openai", "openrouter"], default=None, help="Use an LLM provider instead of deterministic summary.")
    summarize.add_argument("--model", default=None, help="Model name for the selected LLM provider.")
    summarize.set_defaults(rebuild=False)

    status = sub.add_parser("status", help="Show database and git status for the project.")
    status.add_argument("--all-projects", action="store_true", help="Show global database project stats.")

    timeline = sub.add_parser("timeline", help="Show recent normalized events.")
    timeline.add_argument("--limit", type=int, default=40)
    timeline.add_argument("--all-projects", action="store_true", help="Show recent events across all projects from the global database.")

    return parser


def cmd_scan(args: argparse.Namespace, project: Path, db_path: Path, quiet: bool = False) -> int:
    codex_home = Path(args.codex_home).expanduser().resolve()
    store = EventStore(db_path)
    scanned = 0
    matched = 0
    inserted = 0
    try:
        if getattr(args, "rebuild", False):
            if getattr(args, "all_projects", False):
                store.clear_all()
            else:
                store.clear_project(project)
        for path in discover_session_files(codex_home):
            scanned += 1
            session, events = parse_session_file(path)
            if session is None:
                continue
            if getattr(args, "all_projects", False):
                if session.cwd is None:
                    continue
            elif not session_matches_project(session.cwd, project):
                continue
            matched += 1
            store.upsert_session(session)
            inserted += store.insert_events(events)
        store.commit()
    finally:
        store.close()
    if not quiet:
        print(f"Scanned {scanned} Codex session file(s).")
        if getattr(args, "all_projects", False):
            print(f"Matched {matched} session file(s) across all projects.")
        else:
            print(f"Matched {matched} session file(s) for {project}.")
        print(f"Inserted {inserted} new event(s).")
        print(f"Database: {db_path}")
    return 0


def cmd_today(args: argparse.Namespace, project: Path, db_path: Path) -> int:
    if getattr(args, "all_projects", False):
        facts = load_facts(args, project, db_path)
        print(render_all_projects_facts(facts), end="")
        return 0
    since = parse_since(args.since)
    store = EventStore(db_path)
    try:
        rows = store.events_since(project, since)
    finally:
        store.close()
    print(render_today(project, since, rows, inspect_git(project)), end="")
    return 0


def cmd_facts(args: argparse.Namespace, project: Path, db_path: Path) -> int:
    facts = load_facts(args, project, db_path)
    if args.json:
        if getattr(args, "all_projects", False):
            print(all_projects_facts_to_json(facts), end="")
        else:
            print(facts_to_json(facts), end="")
    else:
        if getattr(args, "all_projects", False):
            print(render_all_projects_facts(facts), end="")
        else:
            print(render_facts(facts), end="")
    return 0


def cmd_summarize(args: argparse.Namespace, project: Path, db_path: Path) -> int:
    facts = load_facts(args, project, db_path)
    prompt = render_summary_prompt(facts)
    if args.prompt:
        print(prompt)
        return 0
    if args.llm == "openai":
        try:
            print(summarize_with_openai(prompt, model=args.model), end="")
        except LLMError as exc:
            print(f"LLM summary unavailable: {exc}")
            print()
            print("Deterministic fallback:")
            print(deterministic_summary(facts), end="")
        return 0
    if args.llm == "openrouter":
        try:
            print(summarize_with_openrouter(prompt, model=args.model), end="")
        except LLMError as exc:
            print(f"LLM summary unavailable: {exc}")
            print()
            print("Deterministic fallback:")
            print(deterministic_summary(facts), end="")
        return 0
    print(deterministic_summary(facts), end="")
    return 0


def cmd_status(args: argparse.Namespace, project: Path, db_path: Path) -> int:
    store = EventStore(db_path)
    try:
        if getattr(args, "all_projects", False):
            stats = store.stats()
            projects = store.project_stats()
        else:
            stats = store.stats(project)
            projects = []
    finally:
        store.close()
    if getattr(args, "all_projects", False):
        print(render_global_status(db_path, stats, projects), end="")
    else:
        print(render_status(project, inspect_git(project), stats), end="")
    return 0


def cmd_timeline(args: argparse.Namespace, project: Path, db_path: Path) -> int:
    store = EventStore(db_path)
    try:
        if getattr(args, "all_projects", False):
            rows = store.recent_events_all_projects(args.limit)
        else:
            rows = store.recent_events(project, args.limit)
    finally:
        store.close()
    print(render_timeline(rows), end="")
    return 0


def load_facts(args: argparse.Namespace, project: Path, db_path: Path):
    since = parse_since(args.since)
    store = EventStore(db_path)
    try:
        if getattr(args, "all_projects", False):
            rows = store.events_since_all_projects(since)
        else:
            rows = store.events_since(project, since)
    finally:
        store.close()
    if getattr(args, "all_projects", False):
        return build_all_projects_facts(since, rows)
    return build_work_facts(project, since, rows, inspect_git(project))


def default_db_path_for(project: Path, all_projects: bool) -> Path:
    return default_global_db_path() if all_projects else default_db_path(project)


def render_global_status(db_path: Path, stats: dict[str, object], projects: list[dict[str, object]]) -> str:
    lines = [
        f"Global Recap status for {db_path}",
        "",
        f"Stored sessions: {stats['sessions']}",
        f"Stored events: {stats['events']}",
    ]
    kinds = stats.get("kinds") or {}
    if isinstance(kinds, dict) and kinds:
        lines.append("Event kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    lines.extend(["", f"Projects: {len(projects)}"])
    for project in projects[:20]:
        lines.append(
            f"- {project['project_path']}: {project['events']} events, "
            f"{project['sessions']} thread(s), updated {project['updated_at']}"
        )
    if len(projects) > 20:
        lines.append(f"- ...and {len(projects) - 20} more")
    return "\n".join(lines).rstrip() + "\n"


def session_matches_project(session_cwd: Path | None, project: Path) -> bool:
    if session_cwd is None:
        return False
    session_path = session_cwd.resolve()
    project = project.resolve()
    return session_path == project or project in session_path.parents


def parse_since(value: str | None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_TZ)
        return parsed
    today = datetime.now(LOCAL_TZ).date()
    return datetime.combine(today, time.min, tzinfo=LOCAL_TZ)
