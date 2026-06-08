# Recap

Recap is a local CLI for turning Codex work into a useful project memory.

The MVP is Codex-first:

- ingest Codex JSONL sessions from `~/.codex/sessions` and `~/.codex/archived_sessions`
- normalize user messages, assistant messages, tool calls, shell commands, and outputs into SQLite
- join the Codex timeline with the current git state
- report what happened today and what might need attention

## Usage

Run from a project directory:

```bash
python3 -m recap scan
python3 -m recap scan --all-projects
python3 -m recap today
python3 -m recap today --all-projects
python3 -m recap facts
python3 -m recap summarize
python3 -m recap tui
python3 -m recap status
python3 -m recap timeline
```

By default Recap stores data in `.recap/recap.sqlite` in the current directory and filters Codex sessions to the current project path.

Useful options:

```bash
python3 -m recap scan --project /path/to/project
python3 -m recap scan --rebuild
python3 -m recap scan --all-projects --rebuild
python3 -m recap today --since 2026-06-07
python3 -m recap facts --json
python3 -m recap facts --all-projects
python3 -m recap summarize --prompt
python3 -m recap summarize --all-projects
python3 -m recap summarize --language chinese
python3 -m recap summarize --llm openai
python3 -m recap summarize --llm openrouter
python3 -m recap timeline --limit 40
python3 -m recap timeline --all-projects --limit 40
```

Project-local mode stores data in `PROJECT/.recap/recap.sqlite`.
All-project mode stores data in `~/.recap/recap.sqlite`, scans every Codex session with a project path, then groups output by project and by thread.

`summarize` is deterministic by default. `summarize --llm openai` sends a compact work-facts prompt to OpenAI when `OPENAI_API_KEY` is set; otherwise it falls back gracefully.
`summarize --llm openrouter` uses `OPENROUTER_API_KEY` and defaults to `OPENROUTER_MODEL=openai/gpt-4.1`.
Use `summarize --language chinese` for Simplified Chinese output, or run `python3 -m recap tui` to choose language, scope, LLM provider, model, and scan mode interactively. After the language choice, the TUI prompts and status messages switch to the selected language too.

## OpenRouter Setup

Create an API key at OpenRouter, then add it to your shell:

```bash
echo 'export OPENROUTER_API_KEY="sk-or-..."' >> ~/.zshrc
echo 'export OPENROUTER_MODEL="openai/gpt-4.1"' >> ~/.zshrc
source ~/.zshrc
```

Then run:

```bash
python3 -m recap summarize --llm openrouter
```

Optional environment variables:

```bash
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
export OPENROUTER_REFERER="https://github.com/ysntony/recap"
export OPENROUTER_TITLE="Recap"
```

## Current Scope

This first version intentionally avoids a daemon, Claude ingestion, and Kimi ingestion. The core is a pull-based Codex adapter plus a small event ledger and a lightweight terminal UI. Once this feels useful, daemon/watch mode and additional adapters can be added around the same event model.
