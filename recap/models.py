from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodexSession:
    thread_id: str
    path: Path
    cwd: Path | None
    started_at: datetime | None
    updated_at: datetime | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecapEvent:
    event_id: str
    thread_id: str
    source: str
    project_path: Path | None
    timestamp: datetime
    kind: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
