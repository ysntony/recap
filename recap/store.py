from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import CodexSession, RecapEvent


def default_db_path(project: Path) -> Path:
    return project / ".recap" / "recap.sqlite"


def default_global_db_path() -> Path:
    return Path.home() / ".recap" / "recap.sqlite"


class EventStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.migrate()

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        self.conn.executescript(
            """
            create table if not exists sessions (
              thread_id text primary key,
              source text not null,
              rollout_path text not null,
              project_path text,
              started_at text,
              updated_at text,
              title text,
              metadata_json text not null
            );

            create table if not exists events (
              event_id text primary key,
              thread_id text not null,
              source text not null,
              project_path text,
              ts text not null,
              kind text not null,
              text text not null,
              metadata_json text not null
            );

            create index if not exists idx_events_project_ts on events(project_path, ts);
            create index if not exists idx_events_kind_ts on events(kind, ts);
            create index if not exists idx_events_thread on events(thread_id);
            """
        )
        self.conn.commit()

    def upsert_session(self, session: CodexSession) -> None:
        self.conn.execute(
            """
            insert into sessions(thread_id, source, rollout_path, project_path, started_at, updated_at, title, metadata_json)
            values (?, 'codex', ?, ?, ?, ?, ?, ?)
            on conflict(thread_id) do update set
              rollout_path=excluded.rollout_path,
              project_path=excluded.project_path,
              started_at=coalesce(excluded.started_at, sessions.started_at),
              updated_at=excluded.updated_at,
              title=coalesce(excluded.title, sessions.title),
              metadata_json=excluded.metadata_json
            """,
            (
                session.thread_id,
                str(session.path),
                str(session.cwd) if session.cwd else None,
                iso(session.started_at),
                iso(session.updated_at),
                session.title,
                json.dumps(session.metadata, sort_keys=True),
            ),
        )

    def insert_events(self, events: Iterable[RecapEvent]) -> int:
        count = 0
        for event in events:
            cur = self.conn.execute(
                """
                insert or ignore into events(event_id, thread_id, source, project_path, ts, kind, text, metadata_json)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.thread_id,
                    event.source,
                    str(event.project_path) if event.project_path else None,
                    iso(event.timestamp),
                    event.kind,
                    event.text,
                    json.dumps(event.metadata, sort_keys=True),
                ),
            )
            count += cur.rowcount
        return count

    def commit(self) -> None:
        self.conn.commit()

    def clear_project(self, project: Path) -> None:
        project_path = str(project.resolve())
        self.conn.execute("delete from events where project_path = ?", (project_path,))
        self.conn.execute("delete from sessions where project_path = ?", (project_path,))

    def clear_all(self) -> None:
        self.conn.execute("delete from events")
        self.conn.execute("delete from sessions")

    def events_since(self, project: Path, since: datetime) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                select * from events
                where project_path = ? and ts >= ?
                order by ts asc
                """,
                (str(project.resolve()), iso(since)),
            )
        )

    def events_since_all_projects(self, since: datetime) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                select * from events
                where project_path is not null and ts >= ?
                order by project_path asc, ts asc
                """,
                (iso(since),),
            )
        )

    def recent_events(self, project: Path, limit: int) -> list[sqlite3.Row]:
        rows = list(
            self.conn.execute(
                """
                select * from events
                where project_path = ?
                order by ts desc
                limit ?
                """,
                (str(project.resolve()), limit),
            )
        )
        return list(reversed(rows))

    def recent_events_all_projects(self, limit: int) -> list[sqlite3.Row]:
        rows = list(
            self.conn.execute(
                """
                select * from events
                where project_path is not null
                order by ts desc
                limit ?
                """,
                (limit,),
            )
        )
        return list(reversed(rows))

    def stats(self, project: Path | None = None) -> dict[str, object]:
        where = ""
        params: tuple[str, ...] = ()
        if project:
            where = "where project_path = ?"
            params = (str(project.resolve()),)
        rows = self.conn.execute(f"select kind, count(*) as n from events {where} group by kind", params).fetchall()
        kinds = Counter({row["kind"]: row["n"] for row in rows})
        sessions = self.conn.execute(
            f"select count(*) as n from sessions {'where project_path = ?' if project else ''}",
            params,
        ).fetchone()["n"]
        return {"sessions": sessions, "events": sum(kinds.values()), "kinds": dict(kinds)}

    def project_stats(self) -> list[dict[str, object]]:
        rows = self.conn.execute(
            """
            select project_path, count(distinct thread_id) as sessions, count(*) as events, max(ts) as updated_at
            from events
            where project_path is not null
            group by project_path
            order by updated_at desc
            """
        ).fetchall()
        return [dict(row) for row in rows]


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
