"""Conversation summarisation.

When loaded history exceeds SUMMARISE_THRESHOLD_TOKENS, the older messages are
condensed into a single summary that replaces them in the LLM context. The
summary is persisted to PostgreSQL so it survives server restarts.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI

from .history import (
    KEEP_RECENT_MESSAGES,
    SUMMARISE_THRESHOLD_TOKENS,
    save_message,
)

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        azure_endpoint=os.environ["OPENAI_BASE_URL"],
        api_version=os.environ.get("API_VERSION", "2024-12-01-preview"),
    )


def _deployment() -> str:
    return os.environ.get("MODEL_NAME", "gpt-5.4-mini").strip('"')


def maybe_summarise(
    conversation_id: str,
    messages: list[dict],
    total_tokens: int,
    context_mode: str,
) -> list[dict]:
    """Summarise old messages if the token budget is exceeded.

    If a summary already exists (context_mode == 'summarised') or we're under
    the budget, returns messages unchanged. Otherwise condenses older messages
    into a summary, persists it, and returns the updated context.
    """
    if context_mode == "summarised":
        return messages  # already summarised

    if total_tokens < SUMMARISE_THRESHOLD_TOKENS:
        return messages  # under budget, nothing to do

    # Only summarise user/assistant pairs
    chat_messages = [m for m in messages if m["role"] in ("user", "assistant")]
    if len(chat_messages) <= KEEP_RECENT_MESSAGES:
        return messages  # not enough history

    to_summarise = chat_messages[:-KEEP_RECENT_MESSAGES]
    recent = chat_messages[-KEEP_RECENT_MESSAGES:]

    transcript = "\n".join(
        f"{m['role'].upper()}: {m.get('content', '')}" for m in to_summarise
    )

    response = _client().chat.completions.create(
        model=_deployment(),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are summarising a BI assistant conversation. "
                    "Capture the key findings, data established, SQL results discussed, "
                    "and any decisions made. Be concise — under 200 words. "
                    "Do not include pleasantries or meta-commentary."
                ),
            },
            {
                "role": "user",
                "content": f"Summarise this conversation:\n\n{transcript}",
            },
        ],
        max_completion_tokens=300,
    )

    summary_text = response.choices[0].message.content or ""
    save_message(conversation_id, "summary", summary_text)

    # Return summary as a system message + the recent turns
    updated: list[dict] = [
        {"role": "system", "content": f"[Previous conversation summary]\n{summary_text}"}
    ]
    updated.extend(recent)
    return updated
