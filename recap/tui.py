from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path
from typing import TypeVar

from .cli import cmd_scan, load_facts, summarize_facts
from .codex import default_codex_home
from .store import default_global_db_path


T = TypeVar("T")


def run_tui(project: Path, db_path: Path, codex_home: Path | None = None) -> int:
    codex_home = codex_home or default_codex_home()
    print("Recap TUI")
    print("---------")
    print(f"Project: {project}")
    print()

    try:
        all_projects = choose(
            "Scope",
            [
                ("Current project", False),
                ("All projects", True),
            ],
        )
        language = choose(
            "Summary language",
            [
                ("English", "english"),
                ("Chinese", "chinese"),
            ],
        )
        llm = choose(
            "Summary engine",
            [
                ("Deterministic local summary", None),
                (provider_label("openrouter"), "openrouter"),
                (provider_label("openai"), "openai"),
            ],
        )
        model = ask_model(llm)
        scan_mode = choose(
            "Scan mode",
            [
                ("Scan incrementally first", "scan"),
                ("Use existing database", "no_scan"),
                ("Rebuild then scan", "rebuild"),
            ],
        )
        since = input("Since [today]: ").strip() or None
    except KeyboardInterrupt:
        print()
        print("Cancelled.")
        return 130

    summary_db_path = default_global_db_path() if all_projects else db_path
    args = Namespace(
        all_projects=all_projects,
        codex_home=str(codex_home),
        rebuild=scan_mode == "rebuild",
        no_scan=scan_mode == "no_scan",
        since=since,
    )

    print()
    if not args.no_scan:
        cmd_scan(args, project, summary_db_path)
        print()

    facts = load_facts(args, project, summary_db_path)
    if llm:
        print("Using compact work facts with the selected LLM provider.")
    print(summarize_facts(facts, llm=llm, model=model, language=language), end="")
    return 0


def choose(title: str, options: list[tuple[str, T]]) -> T:
    print(title)
    for index, (label, _) in enumerate(options, start=1):
        print(f"  {index}. {label}")
    while True:
        raw = input("Choose [1]: ").strip()
        if not raw:
            return options[0][1]
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(options):
                return options[index - 1][1]
        print(f"Enter a number from 1 to {len(options)}.")


def ask_model(llm: str | None) -> str | None:
    if not llm:
        return None
    default = default_model(llm)
    raw = input(f"Model [{default}]: ").strip()
    return raw or None


def default_model(llm: str) -> str:
    if llm == "openrouter":
        return os.environ.get("OPENROUTER_MODEL", "openai/gpt-4.1")
    return os.environ.get("OPENAI_MODEL", "gpt-5.5")


def provider_label(provider: str) -> str:
    if provider == "openrouter":
        status = "key set" if os.environ.get("OPENROUTER_API_KEY") else "missing OPENROUTER_API_KEY"
        return f"OpenRouter ({status})"
    status = "key set" if os.environ.get("OPENAI_API_KEY") else "missing OPENAI_API_KEY"
    return f"OpenAI ({status})"
