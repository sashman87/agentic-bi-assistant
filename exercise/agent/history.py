"""PostgreSQL conversation and message persistence."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

SUMMARISE_THRESHOLD_TOKENS = 12_000
KEEP_RECENT_MESSAGES = 6


def _connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(os.environ["PG_URL"])


def init_db() -> None:
    """Create tables and indexes if they don't exist."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id     TEXT,
                    title       TEXT,
                    created_at  TIMESTAMPTZ DEFAULT now(),
                    updated_at  TIMESTAMPTZ DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    conversation_id      UUID REFERENCES conversations(id) ON DELETE CASCADE,
                    role                 TEXT NOT NULL,
                    content              TEXT,
                    token_count          INTEGER DEFAULT 0,
                    summarised_up_to_id  UUID,
                    created_at           TIMESTAMPTZ DEFAULT now()
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_conversations_user
                    ON conversations(user_id, updated_at DESC);
            """)
        conn.commit()


def create_conversation(user_id: str, title: str = "New conversation") -> str:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (user_id, title) VALUES (%s, %s) RETURNING id",
                (user_id, title),
            )
            row = cur.fetchone()
        conn.commit()
    return str(row[0])


def update_conversation_title(conversation_id: str, title: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET title = %s WHERE id = %s",
                (title, conversation_id),
            )
        conn.commit()


def get_user_conversations(user_id: str, limit: int = 10) -> list[dict]:
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at,
                       count(m.id) AS message_count
                FROM   conversations c
                LEFT JOIN messages m
                       ON m.conversation_id = c.id AND m.role IN ('user','assistant')
                WHERE  c.user_id = %s
                GROUP  BY c.id
                ORDER  BY c.updated_at DESC
                LIMIT  %s
                """,
                (user_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def estimate_tokens(text: str | None) -> int:
    """Rough estimate: ~4 chars per token."""
    return max(1, len(str(text or "")) // 4)


def save_message(
    conversation_id: str,
    role: str,
    content: str,
    summarised_up_to_id: str | None = None,
) -> str:
    token_count = estimate_tokens(content)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages
                    (conversation_id, role, content, token_count, summarised_up_to_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (conversation_id, role, content, token_count, summarised_up_to_id),
            )
            msg_id = str(cur.fetchone()[0])
            cur.execute(
                "UPDATE conversations SET updated_at = now() WHERE id = %s",
                (conversation_id,),
            )
        conn.commit()
    return msg_id


def load_conversation_for_agent(
    conversation_id: str,
) -> tuple[list[dict], int, str]:
    """Load conversation history for the agent loop.

    Returns:
        (messages_for_llm, total_token_count, context_mode)
        context_mode is 'full' or 'summarised'.
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, role, content, token_count
                FROM   messages
                WHERE  conversation_id = %s
                ORDER  BY created_at ASC
                """,
                (conversation_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        return [], 0, "full"

    total_tokens = sum(r.get("token_count") or 0 for r in rows)

    # If a summary exists, use it + messages after it
    summary_row = next(
        (r for r in reversed(rows) if r["role"] == "summary"), None
    )
    if summary_row:
        summary_idx = next(
            i for i, r in enumerate(rows) if str(r["id"]) == str(summary_row["id"])
        )
        recent = rows[summary_idx + 1 :]
        messages = [
            {
                "role": "system",
                "content": f"[Previous conversation summary]\n{summary_row['content']}",
            }
        ]
        messages.extend(_row_to_message(r) for r in recent if r["role"] in ("user", "assistant"))
        return messages, total_tokens, "summarised"

    # Full history — user and assistant messages only
    messages = [
        _row_to_message(r) for r in rows if r["role"] in ("user", "assistant")
    ]
    return messages, total_tokens, "full"


def _row_to_message(row: dict) -> dict:
    return {"role": row["role"], "content": row.get("content") or ""}


def get_conversation_for_display(conversation_id: str) -> dict[str, Any]:
    """Load display data for the frontend session-resume modal.

    Returns: {summary, recent_messages}
    - summary: the latest AI-generated summary (or None)
    - recent_messages: last 6 user/assistant messages
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, role, content, created_at
                FROM   messages
                WHERE  conversation_id = %s
                  AND  role IN ('user', 'assistant', 'summary')
                ORDER  BY created_at ASC
                """,
                (conversation_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]

    summary_row = next((r for r in reversed(rows) if r["role"] == "summary"), None)
    chat_rows = [r for r in rows if r["role"] in ("user", "assistant")]
    recent = chat_rows[-KEEP_RECENT_MESSAGES:]

    return {
        "summary": summary_row["content"] if summary_row else None,
        "recent_messages": [
            {
                "role": r["role"],
                "content": r["content"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in recent
        ],
    }
