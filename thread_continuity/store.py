from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import MessageRecord, ThreadRecord
from .utils import compact_text, days_old, default_db_path, now_iso, redact_text, sanitize_value


class ThreadStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._has_fts = self._detect_fts()
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _detect_fts(self) -> bool:
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __fts_probe USING fts5(value)")
            self.conn.execute("DROP TABLE IF EXISTS __fts_probe")
            return True
        except sqlite3.OperationalError:
            return False

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS threads (
              thread_id TEXT PRIMARY KEY,
              source TEXT NOT NULL,
              workspace TEXT,
              title TEXT NOT NULL,
              created_at TEXT,
              updated_at TEXT,
              participants_json TEXT NOT NULL,
              derived_json TEXT NOT NULL,
              source_path TEXT NOT NULL,
              source_status TEXT NOT NULL,
              body_available INTEGER NOT NULL,
              indexed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
              message_id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              role TEXT NOT NULL,
              text TEXT NOT NULL,
              timestamp TEXT,
              tool_name TEXT,
              artifacts_json TEXT NOT NULL,
              line_ref TEXT,
              FOREIGN KEY(thread_id) REFERENCES threads(thread_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS source_health (
              source TEXT PRIMARY KEY,
              status_json TEXT NOT NULL,
              checked_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS index_runs (
              run_id INTEGER PRIMARY KEY AUTOINCREMENT,
              source TEXT NOT NULL,
              indexed_threads INTEGER NOT NULL,
              indexed_messages INTEGER NOT NULL,
              started_at TEXT NOT NULL,
              finished_at TEXT NOT NULL,
              warnings_json TEXT NOT NULL
            );
            """
        )
        if self._has_fts:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(message_id, thread_id, text)"
            )
        self.conn.commit()

    def clear_source(self, source: str) -> None:
        if source == "all":
            self.conn.execute("DELETE FROM threads")
            self.conn.execute("DELETE FROM messages")
            if self._has_fts:
                self.conn.execute("DELETE FROM messages_fts")
        else:
            message_ids = [
                row["message_id"]
                for row in self.conn.execute(
                    "SELECT m.message_id FROM messages m JOIN threads t ON t.thread_id = m.thread_id WHERE t.source = ?",
                    (source,),
                )
            ]
            self.conn.execute("DELETE FROM threads WHERE source = ?", (source,))
            self.conn.execute("DELETE FROM messages WHERE thread_id NOT IN (SELECT thread_id FROM threads)")
            if self._has_fts and message_ids:
                self.conn.executemany("DELETE FROM messages_fts WHERE message_id = ?", [(mid,) for mid in message_ids])
        self.conn.commit()

    def upsert_thread(self, record: ThreadRecord) -> int:
        indexed_at = now_iso()
        self.conn.execute(
            """
            INSERT INTO threads (
              thread_id, source, workspace, title, created_at, updated_at, participants_json,
              derived_json, source_path, source_status, body_available, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
              source = excluded.source,
              workspace = excluded.workspace,
              title = excluded.title,
              created_at = excluded.created_at,
              updated_at = excluded.updated_at,
              participants_json = excluded.participants_json,
              derived_json = excluded.derived_json,
              source_path = excluded.source_path,
              source_status = excluded.source_status,
              body_available = excluded.body_available,
              indexed_at = excluded.indexed_at
            """,
            (
                record.thread_id,
                record.source,
                record.workspace,
                record.title,
                record.created_at,
                record.updated_at,
                json.dumps(record.participants, sort_keys=True),
                json.dumps(record.derived.__dict__, sort_keys=True),
                record.source_path,
                record.source_status,
                1 if record.body_available else 0,
                indexed_at,
            ),
        )
        self.conn.execute("DELETE FROM messages WHERE thread_id = ?", (record.thread_id,))
        if self._has_fts:
            self.conn.execute("DELETE FROM messages_fts WHERE thread_id = ?", (record.thread_id,))
        for message in record.messages:
            self._insert_message(record.thread_id, message)
        self.conn.commit()
        return len(record.messages)

    def _insert_message(self, thread_id: str, message: MessageRecord) -> None:
        self.conn.execute(
            """
            INSERT INTO messages (
              message_id, thread_id, role, text, timestamp, tool_name, artifacts_json, line_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                thread_id,
                message.role,
                message.text,
                message.timestamp,
                message.tool_name,
                json.dumps(message.artifacts, sort_keys=True),
                message.line_ref,
            ),
        )
        if self._has_fts:
            self.conn.execute(
                "INSERT INTO messages_fts(message_id, thread_id, text) VALUES (?, ?, ?)",
                (message.message_id, thread_id, message.text),
            )

    def record_health(self, source: str, status: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO source_health(source, status_json, checked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
              status_json = excluded.status_json,
              checked_at = excluded.checked_at
            """,
            (source, json.dumps(status, sort_keys=True), now_iso()),
        )
        self.conn.commit()

    def record_index_run(
        self,
        *,
        source: str,
        indexed_threads: int,
        indexed_messages: int,
        started_at: str,
        warnings: list[str],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO index_runs(source, indexed_threads, indexed_messages, started_at, finished_at, warnings_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (source, indexed_threads, indexed_messages, started_at, now_iso(), json.dumps(warnings)),
        )
        self.conn.commit()

    def index_status(self) -> dict[str, Any]:
        thread_count = self.conn.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"]
        message_count = self.conn.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"]
        last_run = self.conn.execute(
            "SELECT * FROM index_runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        return {
            "db_path": str(self.db_path),
            "fts": self._has_fts,
            "thread_count": thread_count,
            "message_count": message_count,
            "last_run": dict(last_run) if last_run else None,
        }

    def get_thread(self, thread_id: str, *, include_messages: bool = False) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
        if row is None:
            return None
        payload = self._thread_payload(row)
        if include_messages:
            payload["messages"] = [
                self._message_payload(message)
                for message in self.conn.execute(
                    "SELECT * FROM messages WHERE thread_id = ? ORDER BY timestamp, rowid",
                    (thread_id,),
                )
            ]
        return payload

    def search(
        self,
        query: str,
        *,
        workspace: str | None = None,
        source: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if self._has_fts:
            rows = self._search_fts(query, workspace=workspace, source=source, limit=limit * 8)
        else:
            rows = self._search_like(query, workspace=workspace, source=source, limit=limit * 8)
        grouped = self._group_results(rows, query=query, workspace=workspace)
        return grouped[:limit]

    def _search_fts(
        self,
        query: str,
        *,
        workspace: str | None,
        source: str | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        fts_query = _fts_query(query)
        filters = []
        params: list[Any] = [fts_query]
        if workspace:
            filters.append("COALESCE(t.workspace, '') LIKE ?")
            params.append(f"%{workspace}%")
        if source:
            filters.append("t.source = ?")
            params.append(source)
        where = " AND " + " AND ".join(filters) if filters else ""
        sql = f"""
            SELECT t.*, m.message_id, m.role, m.text, m.timestamp, m.tool_name, m.artifacts_json, m.line_ref,
                   bm25(messages_fts) AS rank
            FROM messages_fts
            JOIN messages m ON m.message_id = messages_fts.message_id
            JOIN threads t ON t.thread_id = m.thread_id
            WHERE messages_fts MATCH ? {where}
            ORDER BY rank
            LIMIT ?
        """
        params.append(limit)
        try:
            return list(self.conn.execute(sql, params))
        except sqlite3.OperationalError:
            return self._search_like(query, workspace=workspace, source=source, limit=limit)

    def _search_like(
        self,
        query: str,
        *,
        workspace: str | None,
        source: str | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        terms = [term for term in query.split() if term.strip()]
        filters = []
        params: list[Any] = []
        for term in terms[:8]:
            filters.append("m.text LIKE ?")
            params.append(f"%{term}%")
        if workspace:
            filters.append("COALESCE(t.workspace, '') LIKE ?")
            params.append(f"%{workspace}%")
        if source:
            filters.append("t.source = ?")
            params.append(source)
        where = " AND ".join(filters) if filters else "1 = 1"
        sql = f"""
            SELECT t.*, m.message_id, m.role, m.text, m.timestamp, m.tool_name, m.artifacts_json, m.line_ref,
                   0.0 AS rank
            FROM messages m
            JOIN threads t ON t.thread_id = m.thread_id
            WHERE {where}
            LIMIT ?
        """
        params.append(limit)
        return list(self.conn.execute(sql, params))

    def _group_results(
        self,
        rows: list[sqlite3.Row],
        *,
        query: str,
        workspace: str | None,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            thread_id = row["thread_id"]
            if thread_id not in grouped:
                payload = self._thread_payload(row)
                payload["score"] = 0.0
                payload["why"] = []
                payload["evidence"] = []
                grouped[thread_id] = payload
            result = grouped[thread_id]
            text = row["text"]
            result["score"] += _score_row(row, query=query, workspace=workspace)
            result["evidence"].append(
                {
                    "kind": "message" if row["role"] in {"user", "assistant"} else "tool",
                    "source_ref": row["line_ref"] or row["source_path"],
                    "snippet": compact_text(text, limit=260),
                    "message_id": row["message_id"],
                }
            )
        results = list(grouped.values())
        for result in results:
            result["evidence"] = result["evidence"][:3]
            result["why"] = _why(result, query=query, workspace=workspace)
            result["confidence"] = min(0.98, round(0.2 + result.pop("score") / 10, 2))
            result["warnings"] = _warnings(result)
        results.sort(key=lambda item: (item["confidence"], item.get("updated_at") or ""), reverse=True)
        return results

    def _thread_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        derived = sanitize_value(json.loads(row["derived_json"]))
        return {
            "thread_id": row["thread_id"],
            "source": row["source"],
            "title": row["title"],
            "workspace": row["workspace"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "participants": json.loads(row["participants_json"]),
            "status": derived.get("outcome", "unknown"),
            "derived": derived,
            "source_path": redact_text(row["source_path"]),
            "source_status": row["source_status"],
            "body_available": bool(row["body_available"]),
            "indexed_at": row["indexed_at"],
        }

    def _message_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "role": row["role"],
            "text": redact_text(row["text"]),
            "timestamp": row["timestamp"],
            "tool_name": row["tool_name"],
            "artifacts": sanitize_value(json.loads(row["artifacts_json"])),
            "line_ref": redact_text(row["line_ref"] or "") or None,
        }


def _fts_query(query: str) -> str:
    terms = [term.strip('"*()') for term in query.replace("'", " ").split() if term.strip('"*()')]
    if not terms:
        return '""'
    return " OR ".join(f'"{term}"' for term in terms[:12])


def _score_row(row: sqlite3.Row, *, query: str, workspace: str | None) -> float:
    score = 1.0
    text = row["text"].lower()
    title = row["title"].lower()
    for term in query.lower().split():
        clean = term.strip(".,:;!?")
        if not clean:
            continue
        if clean in title:
            score += 1.25
        if clean in text:
            score += 0.75
    if workspace and row["workspace"] and workspace in row["workspace"]:
        score += 2.0
    age = days_old(row["updated_at"])
    if age is not None:
        if age <= 7:
            score += 1.0
        elif age <= 30:
            score += 0.5
    return score


def _why(result: dict[str, Any], *, query: str, workspace: str | None) -> list[str]:
    reasons: list[str] = []
    derived = result.get("derived", {})
    title = result.get("title", "").lower()
    if any(term.strip(".,:;!?").lower() in title for term in query.split()):
        reasons.append("matched title")
    if derived.get("objective"):
        reasons.append("has objective")
    if derived.get("files_touched"):
        reasons.append("has file/artifact refs")
    if workspace and result.get("workspace") and workspace in result["workspace"]:
        reasons.append("matched workspace")
    if result.get("status") != "unknown":
        reasons.append(f"outcome {result['status']}")
    if not reasons:
        reasons.append("matched message text")
    return reasons[:5]


def _warnings(result: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    age = days_old(result.get("updated_at"))
    if age is None:
        warnings.append("missing updated_at")
    elif age > 14:
        warnings.append(f"stale index candidate: {age} days old")
    if not result.get("body_available"):
        warnings.append("body unavailable")
    if result.get("source_status") != "indexed":
        warnings.append(result.get("source_status", "source warning"))
    return warnings
