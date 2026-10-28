"""SQLite storage for the merged self plugin.

One database holds everything that makes up "one self":
profile (narrative + traits), episodes, catchphrases, people, memories,
advisor log. No other plugin store is touched.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS episodes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         REAL,
    role       TEXT,
    text       TEXT,
    importance REAL DEFAULT 0.5
);
CREATE TABLE IF NOT EXISTS catchphrases (
    phrase TEXT PRIMARY KEY,
    count  INTEGER DEFAULT 0,
    at     REAL
);
CREATE TABLE IF NOT EXISTS members (
    user_id   TEXT NOT NULL,
    group_id  TEXT NOT NULL,
    last_seen REAL,
    PRIMARY KEY(user_id, group_id)
);
CREATE TABLE IF NOT EXISTS people (
    user_id    TEXT PRIMARY KEY,
    name       TEXT,
    first_seen REAL,
    last_seen  REAL,
    msg_count  INTEGER DEFAULT 0,
    warmth     REAL DEFAULT 0.5,
    affinity   REAL DEFAULT 0.0,
    notes      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    speaker_id   TEXT,
    speaker_name TEXT,
    scope        TEXT,
    group_id     TEXT DEFAULT '',
    text         TEXT,
    sensitivity  TEXT,
    shareable    INTEGER DEFAULT 1,
    created_at   REAL
);
CREATE TABLE IF NOT EXISTS advisor_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         REAL,
    source     TEXT,
    question   TEXT,
    answer     TEXT,
    ok         INTEGER DEFAULT 1,
    injected   INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_speaker ON memories(speaker_id);
CREATE INDEX IF NOT EXISTS idx_episodes_at ON episodes(at);
"""

DEFAULTS = {
    "narrative": "",
    "narrative_version": 0,
    "verbosity": 0.45,
    "warmth": 0.35,
    "emoji": 0.15,
    "initiative": 0.2,
    "samples": 0,
    "last_reflection": 0,
    "born_at": 0.0,
}


class SelfStore:
    """Thin wrapper around the plugin's single SQLite database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(memories)").fetchall()
            }
            if "group_id" not in columns:
                conn.execute(
                    "ALTER TABLE memories ADD COLUMN group_id TEXT DEFAULT ''"
                )
        self._seed_profile()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------- profile ----------------

    def _seed_profile(self) -> None:
        with self._conn() as conn:
            for key, value in DEFAULTS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO profile(key, value) VALUES(?, ?)",
                    (key, json.dumps(value)),
                )
            row = conn.execute(
                "SELECT value FROM profile WHERE key='born_at'"
            ).fetchone()
            if row and float(json.loads(row["value"]) or 0) <= 0:
                conn.execute(
                    "UPDATE profile SET value=? WHERE key='born_at'",
                    (json.dumps(time.time()),),
                )

    def profile(self) -> dict[str, Any]:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM profile").fetchall()
        data: dict[str, Any] = dict(DEFAULTS)
        for row in rows:
            try:
                data[row["key"]] = json.loads(row["value"])
            except Exception:
                continue
        return data

    def set_profile(self, **values: Any) -> None:
        with self._conn() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO profile(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )

    # ---------------- episodes ----------------

    def add_episode(
        self,
        role: str,
        text: str,
        importance: float = 0.5,
        at: float | None = None,
        keep: int = 2000,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO episodes(at, role, text, importance) VALUES(?,?,?,?)",
                (float(at or time.time()), role, text[:400], importance),
            )
            # Keep the table bounded; old episodes are cheap to drop.
            conn.execute(
                "DELETE FROM episodes WHERE id NOT IN "
                "(SELECT id FROM episodes ORDER BY id DESC LIMIT ?)",
                (max(50, int(keep)),),
            )

    def episode_exists(self, role: str, text: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM episodes WHERE role=? AND text=? LIMIT 1",
                (role, text[:400]),
            ).fetchone()
        return row is not None

    def recent_episodes(self, limit: int = 4) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT at, role, text FROM episodes ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    # ---------------- catchphrases ----------------

    def bump_catchphrase(self, phrase: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO catchphrases(phrase, count, at) VALUES(?,1,?) "
                "ON CONFLICT(phrase) DO UPDATE SET count=count+1, at=excluded.at",
                (phrase, time.time()),
            )
            conn.execute(
                "DELETE FROM catchphrases WHERE phrase NOT IN "
                "(SELECT phrase FROM catchphrases ORDER BY count DESC LIMIT 40)"
            )

    def top_catchphrases(self, limit: int = 3, min_count: int = 1) -> list[str]:
        """Most frequent phrases; ``min_count`` filters one-off noise.

        The prompt side passes ``min_count=2``: a phrase said twice is a habit,
        a phrase said once is usually just a sentence fragment. The panel keeps
        ``min_count=1`` so the admin can still see everything that was learned.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT phrase FROM catchphrases WHERE count >= ? "
                "ORDER BY count DESC, at DESC LIMIT ?",
                (max(1, int(min_count)), int(limit)),
            ).fetchall()
        return [row["phrase"] for row in rows]

    # ---------------- people ----------------

    def touch_person(self, user_id: str, name: str) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO people(user_id, name, first_seen, last_seen, msg_count) "
                "VALUES(?,?,?,?,1) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "name=excluded.name, last_seen=excluded.last_seen, "
                "msg_count=msg_count+1",
                (user_id, name, now, now),
            )

    def person(self, user_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM people WHERE user_id=?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def nudge_affinity(self, user_id: str, delta: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE people SET affinity=MAX(0.0, MIN(1.0, affinity+?)) "
                "WHERE user_id=?",
                (delta, user_id),
            )

    # ---------------- memories ----------------

    def add_memory(
        self,
        speaker_id: str,
        speaker_name: str,
        scope: str,
        text: str,
        sensitivity: str,
        shareable: int,
        group_id: str = "",
        at: float | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO memories("
                "speaker_id, speaker_name, scope, group_id, text, sensitivity, "
                "shareable, created_at"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (
                    speaker_id,
                    speaker_name,
                    scope,
                    group_id,
                    text[:600],
                    sensitivity,
                    shareable,
                    float(at or time.time()),
                ),
            )

    def find_memories(
        self, person: str, limit: int = 20, group_id: str = "", scope: str = ""
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT speaker_id, speaker_name, scope, group_id, text, sensitivity, "
            "shareable, created_at FROM memories "
            "WHERE (speaker_name LIKE ? OR speaker_id=?)"
        )
        params: list[Any] = [f"%{person}%", person]
        if scope:
            query += " AND scope=?"
            params.append(scope)
        if group_id:
            query += " AND group_id=?"
            params.append(group_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def groups_of(self, user_id: str) -> list[str]:
        """Groups a user has been seen in, from members then memories."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT group_id FROM members WHERE user_id=?",
                (user_id,),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT DISTINCT group_id FROM memories "
                    "WHERE speaker_id=? AND group_id IS NOT NULL AND group_id<>''",
                    (user_id,),
                ).fetchall()
        return [str(row["group_id"]) for row in rows]

    def touch_member(self, user_id: str, group_id: str) -> None:
        if not user_id or not group_id:
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO members(user_id, group_id, last_seen) VALUES(?,?,?) "
                "ON CONFLICT(user_id, group_id) DO UPDATE SET last_seen=excluded.last_seen",
                (user_id, group_id, time.time()),
            )

    def find_memories_for_private(
        self, person: str, requester_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Rows visible in a private chat.

        Private rows about the person, plus public group chatter from groups the
        requester is also in. Without the membership check any private user
        could pull any group's conversation.
        """
        groups = self.groups_of(requester_id)
        placeholders = ",".join("?" for _ in groups) if groups else "NULL"
        query = (
            "SELECT speaker_id, speaker_name, scope, group_id, text, sensitivity, "
            "shareable, created_at FROM memories "
            "WHERE (speaker_name LIKE ? OR speaker_id=?) AND ("
            " scope='private'"
            " OR (scope='group' AND sensitivity='low' AND shareable=1"
            f"     AND group_id IN ({placeholders}))"
            ") ORDER BY created_at DESC LIMIT ?"
        )
        params: list[Any] = [f"%{person}%", person, *groups, limit]
        with self._conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def list_people_names(self, limit: int = 200) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name FROM people WHERE name IS NOT NULL AND name <> '' "
                "ORDER BY msg_count DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [str(row["name"]) for row in rows]

    # ---------------- advisor ----------------

    def log_advisor(
        self,
        source: str,
        question: str,
        answer: str,
        ok: bool,
        injected: bool,
        latency_ms: int,
    ) -> int:
        """Record one advisor call and return its row id."""
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO advisor_log(at, source, question, answer, ok, injected, latency_ms) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    time.time(),
                    source,
                    question[:500],
                    answer[:2000],
                    1 if ok else 0,
                    1 if injected else 0,
                    int(latency_ms),
                ),
            )
            row_id = int(cursor.lastrowid or 0)
            conn.execute(
                "DELETE FROM advisor_log WHERE id NOT IN "
                "(SELECT id FROM advisor_log ORDER BY id DESC LIMIT 200)"
            )
        return row_id

    def advisor_stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS calls, SUM(ok=0) AS errors, "
                "AVG(latency_ms) AS avg_ms FROM advisor_log"
            ).fetchone()
        return {
            "calls": int(row["calls"] or 0),
            "errors": int(row["errors"] or 0),
            "avg_ms": int(row["avg_ms"] or 0),
        }

    def mark_injected(self, row_id: int) -> None:
        """Flag one specific advisor call as actually used in a reply.

        Marking by id instead of MAX(id) keeps concurrent calls from flagging
        each other's rows.
        """
        if not row_id:
            return
        with self._conn() as conn:
            conn.execute(
                "UPDATE advisor_log SET injected=1 WHERE id=?", (int(row_id),)
            )

    def recent_advisor(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT at, source, question, answer, ok, injected, latency_ms "
                "FROM advisor_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------- aggregates for the panel ----------------

    def list_people(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT user_id, name, first_seen, last_seen, msg_count, affinity "
                "FROM people ORDER BY msg_count DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def memory_count(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def count_people(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM people").fetchone()[0])

    def episode_count(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])

    def reset_narrative(self) -> None:
        # Bump the version too: a reflection that read the old text must not
        # write it back over the reset.
        version = int(float(self.profile().get("narrative_version") or 0)) + 1
        self.set_profile(
            narrative="",
            samples=0,
            last_reflection=0,
            narrative_version=version,
        )

    def append_narrative(
        self, text: str, max_chars: int = 2000, max_entry: int = 200
    ) -> tuple[bool, str]:
        """Append one line to the self narrative; never overwrites.

        The text is sanitized so it cannot close the prompt wrapper, capped per
        entry so "append only" cannot be used as a bulk rewrite, and the
        reflection marker plus a version counter are bumped so a concurrent
        reflection discards its stale copy.

        Returns:
            (ok, message) — message is the new narrative on success.
        """
        addition = str(text or "").strip()
        if not addition:
            return False, "没有可写的内容。"
        addition = re.sub(
            r"</?(?:internal|private)_[^>]*>", "", addition, flags=re.I
        ).strip()
        if not addition:
            return False, "内容里只有标签，没写正文。"
        if len(addition) > max_entry:
            return False, f"单次最多 {max_entry} 字，这段太长了。"
        profile = self.profile()
        current = str(profile.get("narrative") or "")
        if len(current) + len(addition) + 1 > max_chars:
            return False, f"叙事最多 {max_chars} 字，这一段写不下了。"
        merged = f"{current}\n{addition}".strip() if current else addition
        samples = int(float(profile.get("samples") or 0))
        version = int(float(profile.get("narrative_version") or 0)) + 1
        self.set_profile(
            narrative=merged,
            last_reflection=samples,
            narrative_version=version,
        )
        return True, merged
