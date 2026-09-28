"""SQLite persistence for links and individual click timestamps."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import secrets
import sqlite3
import string


ALPHABET = string.ascii_letters + string.digits
CODE_LENGTH = 10
MAX_CODE_ATTEMPTS = 8


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


class CodeExhaustedError(Exception):
    """A unique random code could not be allocated."""


class SQLiteStore:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS links (
                    code TEXT PRIMARY KEY,
                    destination TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    click_count INTEGER NOT NULL DEFAULT 0 CHECK (click_count >= 0),
                    last_clicked_at TEXT
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS clicks (
                    id INTEGER PRIMARY KEY,
                    code TEXT NOT NULL REFERENCES links(code) ON DELETE CASCADE,
                    clicked_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS clicks_code_id ON clicks(code, id DESC)"
            )

    def create_link(self, destination: str) -> dict[str, str]:
        created_at = utc_now()
        with closing(self._connect()) as connection:
            for _ in range(MAX_CODE_ATTEMPTS):
                code = new_code()
                try:
                    with connection:
                        connection.execute(
                            "INSERT INTO links (code, destination, created_at) VALUES (?, ?, ?)",
                            (code, destination, created_at),
                        )
                    return {"code": code, "url": destination, "created_at": created_at}
                except sqlite3.IntegrityError:
                    continue
        raise CodeExhaustedError

    def destination_for(self, code: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT destination FROM links WHERE code = ?", (code,)
            ).fetchone()
            return row["destination"] if row else None

    def record_click(self, code: str) -> str | None:
        clicked_at = utc_now()
        with closing(self._connect()) as connection, connection:
            # Reserve the write lock before reading, so concurrent clicks cannot lose updates.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT destination FROM links WHERE code = ?", (code,)
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE links
                   SET click_count = click_count + 1, last_clicked_at = ?
                   WHERE code = ?""",
                (clicked_at, code),
            )
            connection.execute(
                "INSERT INTO clicks (code, clicked_at) VALUES (?, ?)",
                (code, clicked_at),
            )
            connection.execute(
                """DELETE FROM clicks WHERE code = ? AND id NOT IN (
                    SELECT id FROM clicks WHERE code = ? ORDER BY id DESC LIMIT 20
                )""",
                (code, code),
            )
            return row["destination"]

    def stats_for(self, code: str) -> dict | None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN")
            row = connection.execute(
                """SELECT code, destination, created_at, click_count, last_clicked_at
                   FROM links WHERE code = ?""",
                (code,),
            ).fetchone()
            if row is None:
                return None
            recent_clicks = connection.execute(
                "SELECT clicked_at FROM clicks WHERE code = ? ORDER BY id DESC LIMIT 20",
                (code,),
            ).fetchall()
            return {
                "code": row["code"],
                "url": row["destination"],
                "created_at": row["created_at"],
                "click_count": row["click_count"],
                "last_clicked_at": row["last_clicked_at"],
                "recent_clicks": [click["clicked_at"] for click in recent_clicks],
            }

    def healthy(self) -> bool:
        with closing(self._connect()) as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1
