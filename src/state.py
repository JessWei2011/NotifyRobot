"""SQLite-backed delivery and acknowledgement state."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


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
            CREATE TABLE IF NOT EXISTS dispositions (
                disposition_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                reason TEXT NOT NULL,
                exit_notified_at TEXT
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

    def track_disposition(
        self, disposition_id: str, market: str, code: str, name: str,
        start_date: str, end_date: str, reason: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO dispositions (disposition_id, market, code, name, start_date, end_date, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(disposition_id) DO UPDATE SET
                market=excluded.market, code=excluded.code, name=excluded.name,
                start_date=excluded.start_date, end_date=excluded.end_date, reason=excluded.reason
            """,
            (disposition_id, market, code, name, start_date, end_date, reason),
        )
        self.connection.commit()

    def pending_disposition_exits(self, today: str):
        return self.connection.execute(
            """
            SELECT disposition_id, market, code, name, start_date, end_date, reason
            FROM dispositions
            WHERE end_date < ? AND exit_notified_at IS NULL
            """,
            (today,),
        ).fetchall()

    def record_disposition_exit(self, disposition_id: str) -> None:
        self.connection.execute(
            "UPDATE dispositions SET exit_notified_at = ? WHERE disposition_id = ?",
            (_now(), disposition_id),
        )
        self.connection.commit()

    def get_market_amount_snapshot(self, trade_date: str) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key = ?",
            (f"market_amount_summary_{trade_date}",),
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except Exception:
                return None
        return None

    def set_market_amount_snapshot(self, trade_date: str, summary: Dict[str, Any], status: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (f"market_amount_summary_{trade_date}", json.dumps(summary)),
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (f"market_amount_status_{trade_date}", status),
        )
        self.connection.commit()

    def get_market_amount_status(self, trade_date: str) -> Optional[str]:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key = ?",
            (f"market_amount_status_{trade_date}",),
        ).fetchone()
        return row[0] if row else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
