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
python3 -m recap today
python3 -m recap facts
python3 -m recap summarize
python3 -m recap status
python3 -m recap timeline
```

By default Recap stores data in `.recap/recap.sqlite` in the current directory and filters Codex sessions to the current project path.

Useful options:

```bash
python3 -m recap scan --project /path/to/project
python3 -m recap scan --rebuild
python3 -m recap today --since 2026-06-07
python3 -m recap facts --json
python3 -m recap summarize --prompt
python3 -m recap summarize --llm openai
python3 -m recap timeline --limit 40
```

`summarize` is deterministic by default. `summarize --llm openai` sends a compact work-facts prompt to OpenAI when `OPENAI_API_KEY` is set; otherwise it falls back gracefully.

## Current Scope

This first version intentionally avoids a daemon, TUI, Claude ingestion, and Kimi ingestion. The core is a pull-based Codex adapter plus a small event ledger. Once this feels useful, daemon/watch mode and additional adapters can be added around the same event model.
