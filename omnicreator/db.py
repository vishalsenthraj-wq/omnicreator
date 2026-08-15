"""SQLite setup and CRUD helpers for OmniCreator AI comment triage."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "omnicreator.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ig_comment_id TEXT UNIQUE NOT NULL,
    ig_media_id TEXT NOT NULL,
    username TEXT NOT NULL,
    text TEXT NOT NULL,
    category TEXT,
    confidence REAL,
    summary TEXT,
    suggested_reply TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING_CLASSIFICATION',
    is_vip INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    posted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_comments_ig_comment_id ON comments(ig_comment_id);
CREATE INDEX IF NOT EXISTS idx_comments_status ON comments(status);
"""


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def comment_exists(conn, ig_comment_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM comments WHERE ig_comment_id = ?", (ig_comment_id,)
    ).fetchone()
    return row is not None


def insert_comment(conn, ig_comment_id: str, ig_media_id: str, username: str, text: str) -> int:
    cur = conn.execute(
        """INSERT INTO comments (ig_comment_id, ig_media_id, username, text, status, created_at)
           VALUES (?, ?, ?, ?, 'PENDING_CLASSIFICATION', ?)""",
        (ig_comment_id, ig_media_id, username, text, now_iso()),
    )
    return cur.lastrowid


def update_classification(conn, comment_id: int, category: str, confidence: float,
                           summary: str | None, suggested_reply: str | None,
                           status: str, is_vip: bool):
    conn.execute(
        """UPDATE comments SET category = ?, confidence = ?, summary = ?,
           suggested_reply = ?, status = ?, is_vip = ? WHERE id = ?""",
        (category, confidence, summary, suggested_reply, status, int(is_vip), comment_id),
    )


def get_comment(conn, comment_id: int):
    return conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()


def mark_posted(conn, comment_id: int, final_reply_text: str):
    conn.execute(
        """UPDATE comments SET status = 'POSTED', suggested_reply = ?, posted_at = ?
           WHERE id = ?""",
        (final_reply_text, now_iso(), comment_id),
    )


def mark_rejected(conn, comment_id: int):
    conn.execute("UPDATE comments SET status = 'REJECTED' WHERE id = ?", (comment_id,))


def list_comments(conn):
    return conn.execute("SELECT * FROM comments ORDER BY created_at DESC").fetchall()


def list_leads(conn):
    return conn.execute(
        "SELECT * FROM comments WHERE category = 'BUSINESS_COLLABORATION' ORDER BY created_at DESC"
    ).fetchall()


def get_stats(conn):
    total = conn.execute("SELECT COUNT(*) c FROM comments").fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM comments WHERE status = 'PENDING_APPROVAL'"
    ).fetchone()["c"]
    vip = conn.execute(
        "SELECT COUNT(*) c FROM comments WHERE category = 'BUSINESS_COLLABORATION'"
    ).fetchone()["c"]
    posted = conn.execute(
        "SELECT COUNT(*) c FROM comments WHERE status = 'POSTED'"
    ).fetchone()["c"]
    spam = conn.execute(
        "SELECT COUNT(*) c FROM comments WHERE status = 'SPAM_LOGGED'"
    ).fetchone()["c"]
    return {
        "total_comments": total,
        "pending_approvals": pending,
        "vip_leads": vip,
        "replies_posted": posted,
        "spam_filtered": spam,
    }
