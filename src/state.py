"""SQLite-backed delivery and acknowledgement state."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class NotificationState:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS deliveries (
                trade_date TEXT NOT NULL,
                report_type TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                acknowledged_at TEXT,
                PRIMARY KEY (trade_date, report_type)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS event_notifications (
                event_id TEXT PRIMARY KEY,
                notified_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def was_sent(self, trade_date: str, report_type: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM deliveries WHERE trade_date = ? AND report_type = ?",
            (trade_date, report_type),
        ).fetchone()
        return row is not None

    def record_delivery(self, trade_date: str, report_type: str, message_id: int) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO deliveries
                (trade_date, report_type, message_id, sent_at, acknowledged_at)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (trade_date, report_type, message_id, _now()),
        )
        self.connection.commit()

    def acknowledge(self, trade_date: str, report_type: str) -> bool:
        cursor = self.connection.execute(
            """
            UPDATE deliveries
            SET acknowledged_at = COALESCE(acknowledged_at, ?)
            WHERE trade_date = ? AND report_type = ?
            """,
            (_now(), trade_date, report_type),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def get_offset(self) -> Optional[int]:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key = 'telegram_update_offset'"
        ).fetchone()
        return int(row[0]) if row else None

    def set_offset(self, offset: int) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('telegram_update_offset', ?)",
            (str(offset),),
        )
        self.connection.commit()

    def event_was_notified(self, event_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM event_notifications WHERE event_id = ?", (event_id,)
        ).fetchone() is not None

    def record_event_notification(self, event_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO event_notifications (event_id, notified_at) VALUES (?, ?)",
            (event_id, _now()),
        )
        self.connection.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
