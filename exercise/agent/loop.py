"""The core agent loop — raw Azure OpenAI function-calling.

One call to run() handles a single user turn:
  1. Load conversation history from PostgreSQL.
  2. Trigger summarisation if over the token budget.
  3. Build the messages array and call the LLM.
  4. Execute tool calls, append results, loop.
  5. When the model calls respond(), return the structured payload.

Max turns: 10. On SQL failure the model gets one retry before being asked to
request clarification from the user.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import AzureOpenAI

from .db import Database
from .history import (
    load_conversation_for_agent,
    save_message,
    update_conversation_title,
)
from .masking import sanitise_sql_for_display
from .prompts import SYSTEM_PROMPT, TOOLS
from .summarise import maybe_summarise
from .tools import (
    tool_describe_table,
    tool_execute_sql,
    tool_get_sample_rows,
    tool_list_tables,
)

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MAX_TURNS = 10


def _client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        azure_endpoint=os.environ["OPENAI_BASE_URL"],
        api_version=os.environ.get("API_VERSION", "2024-12-01-preview"),
    )


def _deployment() -> str:
    return os.environ.get("MODEL_NAME", "gpt-5.4-mini").strip('"')


def _dispatch(
    name: str,
    args: dict,
    db: Database,
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Dispatch a tool call. Returns (result_str, data_or_None, sql_or_None)."""
    if name == "list_tables":
        return tool_list_tables(), None, None

    if name == "describe_table":
        return tool_describe_table(db, args["dataset"], args["table"]), None, None

    if name == "execute_sql":
        result_str, data, sql = tool_execute_sql(db, args["sql"])
        return result_str, data, sql

    if name == "get_sample_rows":
        result_str, data = tool_get_sample_rows(
            db, args["dataset"], args["table"], args.get("n", 5)
        )
        return result_str, data, None

    return f"Unknown tool: {name}", None, None


def run(
    conversation_id: str,
    user_message: str,
    db: Database,
) -> dict[str, Any]:
    """Run the agent for one user turn. Returns the structured response payload."""
    client = _client()
    deployment = _deployment()

    # Load history, check summarisation budget
    history, total_tokens, context_mode = load_conversation_for_agent(conversation_id)
    history = maybe_summarise(conversation_id, history, total_tokens, context_mode)

    # Persist the user message
    save_message(conversation_id, "user", user_message)

    # Use first user message as conversation title if it's short enough
    if not history:
        title = user_message[:60] + ("…" if len(user_message) > 60 else "")
        update_conversation_title(conversation_id, title)

    # Build the LLM message array
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # State tracked across turns
    last_data: dict[str, Any] | None = None
    last_sql: str | None = None
    sql_failure_count = 0
    total_usage: dict[str, int] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    for _turn in range(MAX_TURNS):
        response = client.chat.completions.create(
            model=deployment,
            messages=messages,
            tools=TOOLS,
            tool_choice="required",
        )

        if response.usage:
            total_usage["prompt_tokens"] += response.usage.prompt_tokens
            total_usage["completion_tokens"] += response.usage.completion_tokens
            total_usage["total_tokens"] += response.usage.total_tokens

        choice = response.choices[0]
        msg = choice.message

        if not msg.tool_calls:
            # Shouldn't happen with tool_choice="required", but handle gracefully.
            answer = msg.content or "I was unable to complete your request."
            save_message(conversation_id, "assistant", answer)
            return _build_response(
                answer=answer,
                render="text",
                data=None,
                sql=last_sql,
                needs_clarification=False,
                total_usage=total_usage,
                total_tokens=total_tokens,
                context_mode=context_mode,
            )

        # Append assistant message (with tool_calls) to the thread
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, ValueError):
                args = {}

            # ── respond() → final answer ────────────────────────────────
            if tool_name == "respond":
                answer = args.get("answer", "")
                render = args.get("render", "text")
                sql = args.get("sql") or last_sql or ""
                needs_clarification = args.get("needs_clarification", False)

                save_message(conversation_id, "assistant", answer)

                return _build_response(
                    answer=answer,
                    render=render if not needs_clarification else "text",
                    data=last_data,
                    sql=sql,
                    needs_clarification=needs_clarification,
                    total_usage=total_usage,
                    total_tokens=total_tokens,
                    context_mode=context_mode,
                )

            # ── regular tool ────────────────────────────────────────────
            result_str, data, sql = _dispatch(tool_name, args, db)

            # SQL retry logic
            if tool_name == "execute_sql" and result_str.startswith("SQL error:"):
                sql_failure_count += 1
                if sql_failure_count >= 2:
                    result_str += (
                        "\n\nYou have failed to produce valid SQL twice. "
                        "Stop retrying. Call respond() now to ask the user for "
                        "clarification with needs_clarification=true."
                    )

            if data is not None:
                last_data = data
            if sql is not None:
                last_sql = sql

            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result_str}
            )

    # Hit the turn cap
    answer = (
        "I reached the maximum number of steps without completing your request. "
        "Could you rephrase or break it into a simpler question?"
    )
    save_message(conversation_id, "assistant", answer)
    return _build_response(
        answer=answer,
        render="text",
        data=None,
        sql=None,
        needs_clarification=True,
        total_usage=total_usage,
        total_tokens=total_tokens,
        context_mode=context_mode,
    )


def _build_response(
    *,
    answer: str,
    render: str,
    data: dict | None,
    sql: str | None,
    needs_clarification: bool,
    total_usage: dict,
    total_tokens: int,
    context_mode: str,
) -> dict[str, Any]:
    return {
        "answer": answer,
        "render": render,
        "data": data,
        "sql": sanitise_sql_for_display(sql) if sql else None,
        "needs_clarification": needs_clarification,
        "usage": {
            **total_usage,
            "conversation_total_tokens": total_tokens + total_usage["total_tokens"],
            "context_mode": context_mode,
        },
    }
