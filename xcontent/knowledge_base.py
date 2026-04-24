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

    # Posts: every piece of content the system generates gets stored here.
    # Used for retrieval, inspiration, and training signals.
    db.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            style TEXT NOT NULL,
            content_type TEXT DEFAULT '',
            topic TEXT DEFAULT '',
            focus TEXT DEFAULT '',
            video_id TEXT DEFAULT '',
            video_title TEXT DEFAULT '',
            content TEXT NOT NULL,
            source_videos TEXT DEFAULT '',
            command TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    # Full-text search over the posts table so we can retrieve past posts
    # by topic ("what have I written about Bezos?") cheaply.
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts
        USING fts5(topic, video_title, content, content=posts, content_rowid=rowid)
    """)

    db.executescript("""
        CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
            INSERT INTO posts_fts(rowid, topic, video_title, content)
            VALUES (new.rowid, new.topic, new.video_title, new.content);
        END;
        CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
            INSERT INTO posts_fts(posts_fts, rowid, topic, video_title, content)
            VALUES ('delete', old.rowid, old.topic, old.video_title, old.content);
        END;
        CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN
            INSERT INTO posts_fts(posts_fts, rowid, topic, video_title, content)
            VALUES ('delete', old.rowid, old.topic, old.video_title, old.content);
            INSERT INTO posts_fts(rowid, topic, video_title, content)
            VALUES (new.rowid, new.topic, new.video_title, new.content);
        END;
    """)

    # Track which Typefully drafts we've already synced for edit detection
    db.execute("""
        CREATE TABLE IF NOT EXISTS synced_edits (
            typefully_draft_id TEXT PRIMARY KEY,
            post_id INTEGER,
            similarity REAL,
            synced_at TEXT NOT NULL
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


def get_ideas_for_video(video_id: str) -> list[dict]:
    """Get all ideas previously extracted for a video."""
    db = _get_db()
    rows = db.execute(
        """SELECT * FROM ideas WHERE video_id = ? ORDER BY id""",
        (video_id,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


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


# ── Posts Storage ────────────────────────────────────────────────────


def save_post(
    style: str,
    content: str,
    content_type: str = "",
    topic: str = "",
    focus: str = "",
    video_id: str = "",
    video_title: str = "",
    source_videos: str = "",
    command: str = "",
) -> int:
    """Save a generated post to the knowledge base. Returns the post id."""
    db = _get_db()
    cur = db.execute(
        """INSERT INTO posts (style, content_type, topic, focus, video_id, video_title,
                              content, source_videos, command, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (style, content_type, topic, focus, video_id, video_title,
         content, source_videos, command, datetime.now().isoformat()),
    )
    db.commit()
    post_id = cur.lastrowid
    db.close()
    return post_id


def list_posts(limit: int = 30, style: str = "") -> list[dict]:
    """List recent generated posts."""
    db = _get_db()
    if style:
        rows = db.execute(
            """SELECT id, style, content_type, topic, video_title, command, created_at,
                      substr(content, 1, 120) AS preview
               FROM posts WHERE style = ? ORDER BY created_at DESC LIMIT ?""",
            (style, limit),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT id, style, content_type, topic, video_title, command, created_at,
                      substr(content, 1, 120) AS preview
               FROM posts ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_post(post_id: int) -> dict | None:
    """Get a single post by id."""
    db = _get_db()
    row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def search_posts(query: str, limit: int = 10) -> list[dict]:
    """Full-text search over generated posts."""
    db = _get_db()
    rows = db.execute(
        """SELECT p.id, p.style, p.content_type, p.topic, p.video_title, p.created_at,
                  snippet(posts_fts, 2, '>>>', '<<<', '...', 30) AS excerpt
           FROM posts_fts
           JOIN posts p ON p.rowid = posts_fts.rowid
           WHERE posts_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (query, limit),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def count_posts() -> int:
    db = _get_db()
    row = db.execute("SELECT COUNT(*) AS n FROM posts").fetchone()
    db.close()
    return row["n"] if row else 0


def get_unmined_transcripts(limit: int = 10) -> list[dict]:
    """Get transcripts that haven't had ideas extracted yet."""
    db = _get_db()
    rows = db.execute(
        """SELECT t.video_id, t.video_title, t.channel, t.char_count, t.fetched_at
           FROM transcripts t
           LEFT JOIN ideas i ON t.video_id = i.video_id
           WHERE i.id IS NULL
           ORDER BY t.fetched_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def count_transcripts() -> int:
    db = _get_db()
    row = db.execute("SELECT COUNT(*) AS n FROM transcripts").fetchone()
    db.close()
    return row["n"] if row else 0


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


# ── Edit Detection ──────────────────────────────────────────────────


def find_matching_post(published_text: str, min_similarity: float = 0.3) -> dict | None:
    """Find the generated post that best matches a published text.

    Uses SequenceMatcher to fuzzy-match against all stored posts.
    Returns the best match (with similarity score) or None.
    """
    from difflib import SequenceMatcher

    db = _get_db()
    rows = db.execute(
        "SELECT * FROM posts ORDER BY created_at DESC LIMIT 500"
    ).fetchall()
    db.close()

    best_match = None
    best_ratio = 0.0

    for row in rows:
        ratio = SequenceMatcher(None, row["content"], published_text).ratio()
        if ratio > best_ratio and ratio >= min_similarity:
            best_ratio = ratio
            best_match = dict(row)

    if best_match:
        best_match["similarity"] = best_ratio

    return best_match


def is_draft_synced(typefully_draft_id: str) -> bool:
    db = _get_db()
    row = db.execute(
        "SELECT 1 FROM synced_edits WHERE typefully_draft_id = ?",
        (typefully_draft_id,),
    ).fetchone()
    db.close()
    return row is not None


def mark_draft_synced(typefully_draft_id: str, post_id: int, similarity: float) -> None:
    db = _get_db()
    db.execute(
        """INSERT OR REPLACE INTO synced_edits
           (typefully_draft_id, post_id, similarity, synced_at)
           VALUES (?, ?, ?, ?)""",
        (typefully_draft_id, post_id, similarity, datetime.now().isoformat()),
    )
    db.commit()
    db.close()


def count_feedback() -> int:
    db = _get_db()
    row = db.execute("SELECT COUNT(*) AS n FROM feedback").fetchone()
    db.close()
    return row["n"] if row else 0
