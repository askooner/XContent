"""
Knowledge Base — Local transcript storage with full-text search.

Every transcript you fetch gets stored in a SQLite database. You can
search across all of them instantly — no API calls, no tokens, free.

Also stores generated vs posted pairs for the feedback loop.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(__file__).resolve().parent.parent / "knowledge.db"


def _get_db() -> sqlite3.Connection:
    """Get a connection to the knowledge base, creating tables if needed."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")

    # Transcripts table
    db.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            video_id TEXT PRIMARY KEY,
            video_title TEXT NOT NULL,
            channel TEXT DEFAULT '',
            transcript TEXT NOT NULL,
            char_count INTEGER NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)

    # Full-text search index on transcripts
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts
        USING fts5(video_title, channel, transcript, content=transcripts, content_rowid=rowid)
    """)

    # Triggers to keep FTS in sync
    db.executescript("""
        CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
            INSERT INTO transcripts_fts(rowid, video_title, channel, transcript)
            VALUES (new.rowid, new.video_title, new.channel, new.transcript);
        END;
        CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
            INSERT INTO transcripts_fts(transcripts_fts, rowid, video_title, channel, transcript)
            VALUES ('delete', old.rowid, old.video_title, old.channel, old.transcript);
        END;
        CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
            INSERT INTO transcripts_fts(transcripts_fts, rowid, video_title, channel, transcript)
            VALUES ('delete', old.rowid, old.video_title, old.channel, old.transcript);
            INSERT INTO transcripts_fts(rowid, video_title, channel, transcript)
            VALUES (new.rowid, new.video_title, new.channel, new.transcript);
        END;
    """)

    # Ideas extracted from transcripts
    db.execute("""
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            title TEXT NOT NULL,
            angle TEXT DEFAULT '',
            key_material TEXT DEFAULT '',
            status TEXT DEFAULT 'unused',
            created_at TEXT NOT NULL,
            FOREIGN KEY (video_id) REFERENCES transcripts(video_id)
        )
    """)

    # Feedback loop: generated vs what user actually posted
    db.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            style TEXT NOT NULL,
            content_type TEXT NOT NULL,
            generated_text TEXT NOT NULL,
            posted_text TEXT NOT NULL,
            video_title TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    db.commit()
    return db


# ── Transcript Storage ───────────────────────────────────────────────


def save_transcript(video_id: str, video_title: str, transcript: str, channel: str = "") -> None:
    """Save a transcript to the knowledge base."""
    db = _get_db()
    db.execute(
        """INSERT OR REPLACE INTO transcripts
           (video_id, video_title, channel, transcript, char_count, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (video_id, video_title, channel, transcript, len(transcript), datetime.now().isoformat()),
    )
    db.commit()
    db.close()


def get_transcript(video_id: str) -> dict | None:
    """Get a transcript from the knowledge base by video ID."""
    db = _get_db()
    row = db.execute("SELECT * FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
    db.close()
    if row:
        return dict(row)
    return None


def search_transcripts(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across all stored transcripts. Free, no API tokens."""
    db = _get_db()
    rows = db.execute(
        """SELECT t.video_id, t.video_title, t.channel, t.char_count, t.fetched_at,
                  snippet(transcripts_fts, 2, '>>>', '<<<', '...', 40) AS excerpt
           FROM transcripts_fts
           JOIN transcripts t ON t.rowid = transcripts_fts.rowid
           WHERE transcripts_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (query, limit),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def list_transcripts(limit: int = 50) -> list[dict]:
    """List all stored transcripts."""
    db = _get_db()
    rows = db.execute(
        """SELECT video_id, video_title, channel, char_count, fetched_at
           FROM transcripts ORDER BY fetched_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_transcript_text(video_id: str) -> str | None:
    """Get just the transcript text for a video."""
    db = _get_db()
    row = db.execute("SELECT transcript FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
    db.close()
    if row:
        return row["transcript"]
    return None


# ── Ideas Storage ────────────────────────────────────────────────────


def save_ideas(video_id: str, ideas: list[dict]) -> None:
    """Save extracted ideas for a video."""
    db = _get_db()
    now = datetime.now().isoformat()
    for idea in ideas:
        db.execute(
            """INSERT INTO ideas (video_id, title, angle, key_material, status, created_at)
               VALUES (?, ?, ?, ?, 'unused', ?)""",
            (video_id, idea.get("title", ""), idea.get("angle", ""),
             idea.get("key_material", ""), now),
        )
    db.commit()
    db.close()


def get_unused_ideas(video_id: str | None = None, limit: int = 50) -> list[dict]:
    """Get ideas that haven't been used yet."""
    db = _get_db()
    if video_id:
        rows = db.execute(
            """SELECT i.*, t.video_title FROM ideas i
               JOIN transcripts t ON t.video_id = i.video_id
               WHERE i.video_id = ? AND i.status = 'unused'
               ORDER BY i.created_at DESC LIMIT ?""",
            (video_id, limit),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT i.*, t.video_title FROM ideas i
               JOIN transcripts t ON t.video_id = i.video_id
               WHERE i.status = 'unused'
               ORDER BY i.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def mark_idea_used(idea_id: int) -> None:
    """Mark an idea as used."""
    db = _get_db()
    db.execute("UPDATE ideas SET status = 'used' WHERE id = ?", (idea_id,))
    db.commit()
    db.close()


# ── Feedback Loop ────────────────────────────────────────────────────


def save_feedback(style: str, content_type: str, generated_text: str, posted_text: str,
                  video_title: str = "") -> None:
    """Save a generated-vs-posted pair for the feedback loop."""
    db = _get_db()
    db.execute(
        """INSERT INTO feedback (style, content_type, generated_text, posted_text, video_title, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (style, content_type, generated_text, posted_text, video_title, datetime.now().isoformat()),
    )
    db.commit()
    db.close()


def get_recent_feedback(style: str = "", content_type: str = "", limit: int = 5) -> list[dict]:
    """Get recent feedback pairs to inject into prompts."""
    db = _get_db()
    query = "SELECT * FROM feedback WHERE 1=1"
    params = []
    if style:
        query += " AND style = ?"
        params.append(style)
    if content_type:
        query += " AND content_type = ?"
        params.append(content_type)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    db.close()
    return [dict(r) for r in rows]
