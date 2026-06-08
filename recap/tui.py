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
        language = choose(
            "Summary language / 摘要语言",
            [
                ("English", "english"),
                ("中文", "chinese"),
            ],
            language="bilingual",
        )
        labels = tui_labels(language)
        all_projects = choose(
            labels["scope"],
            [
                (labels["current_project"], False),
                (labels["all_projects"], True),
            ],
            language=language,
        )
        llm = choose(
            labels["summary_engine"],
            [
                (labels["deterministic"], None),
                (provider_label("openrouter", language), "openrouter"),
                (provider_label("openai", language), "openai"),
            ],
            language=language,
        )
        model = ask_model(llm, language)
        scan_mode = choose(
            labels["scan_mode"],
            [
                (labels["scan_incremental"], "scan"),
                (labels["use_existing"], "no_scan"),
                (labels["rebuild_scan"], "rebuild"),
            ],
            language=language,
        )
        since = input(labels["since"]).strip() or None
    except KeyboardInterrupt:
        print()
        language = locals().get("language", "english")
        print(tui_labels(language)["cancelled"])
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
        print(labels["using_llm"])
    print(summarize_facts(facts, llm=llm, model=model, language=language), end="")
    return 0


def choose(title: str, options: list[tuple[str, T]], language: str) -> T:
    labels = tui_labels(language)
    print(title)
    for index, (label, _) in enumerate(options, start=1):
        print(f"  {index}. {label}")
    while True:
        raw = input(labels["choose"]).strip()
        if not raw:
            return options[0][1]
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(options):
                return options[index - 1][1]
        print(labels["choose_error"].format(count=len(options)))


def ask_model(llm: str | None, language: str) -> str | None:
    if not llm:
        return None
    default = default_model(llm)
    raw = input(tui_labels(language)["model"].format(default=default)).strip()
    return raw or None


def default_model(llm: str) -> str:
    if llm == "openrouter":
        return os.environ.get("OPENROUTER_MODEL", "openai/gpt-4.1")
    return os.environ.get("OPENAI_MODEL", "gpt-5.5")


def provider_label(provider: str, language: str) -> str:
    if provider == "openrouter":
        if language == "chinese":
            status = "已设置 key" if os.environ.get("OPENROUTER_API_KEY") else "缺少 OPENROUTER_API_KEY"
        else:
            status = "key set" if os.environ.get("OPENROUTER_API_KEY") else "missing OPENROUTER_API_KEY"
        return f"OpenRouter ({status})"
    if language == "chinese":
        status = "已设置 key" if os.environ.get("OPENAI_API_KEY") else "缺少 OPENAI_API_KEY"
    else:
        status = "key set" if os.environ.get("OPENAI_API_KEY") else "missing OPENAI_API_KEY"
    return f"OpenAI ({status})"


def tui_labels(language: str) -> dict[str, str]:
    if language == "chinese":
        return {
            "scope": "范围",
            "current_project": "当前项目",
            "all_projects": "全部项目",
            "summary_engine": "摘要引擎",
            "deterministic": "本地确定性摘要",
            "scan_mode": "扫描模式",
            "scan_incremental": "先增量扫描",
            "use_existing": "使用现有数据库",
            "rebuild_scan": "重建后扫描",
            "since": "起始时间 [今天]: ",
            "choose": "选择 [1]: ",
            "choose_error": "请输入 1 到 {count} 之间的数字。",
            "model": "模型 [{default}]: ",
            "cancelled": "已取消。",
            "using_llm": "正在使用紧凑 work facts 和所选 LLM provider。",
        }
    if language == "bilingual":
        return {
            "choose": "Choose / 选择 [1]: ",
            "choose_error": "Enter a number from 1 to {count}. / 请输入 1 到 {count} 之间的数字。",
        }
    return {
        "scope": "Scope",
        "current_project": "Current project",
        "all_projects": "All projects",
        "summary_engine": "Summary engine",
        "deterministic": "Deterministic local summary",
        "scan_mode": "Scan mode",
        "scan_incremental": "Scan incrementally first",
        "use_existing": "Use existing database",
        "rebuild_scan": "Rebuild then scan",
        "since": "Since [today]: ",
        "choose": "Choose [1]: ",
        "choose_error": "Enter a number from 1 to {count}.",
        "model": "Model [{default}]: ",
        "cancelled": "Cancelled.",
        "using_llm": "Using compact work facts with the selected LLM provider.",
    }
