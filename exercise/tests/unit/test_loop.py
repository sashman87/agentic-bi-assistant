"""Unit tests for agent/loop.py.

The agent loop depends on Azure OpenAI and PostgreSQL. These tests use mocking
to verify control-flow behaviour (retry logic, turn cap, respond tool handling)
without making live API calls.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_tool_call(name: str, args: dict, call_id: str = "call_001"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _make_response(tool_calls=None, content=None, finish_reason=None):
    msg = MagicMock()
    msg.tool_calls = tool_calls or []
    msg.content = content

    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = finish_reason or ("tool_calls" if tool_calls else "stop")

    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.total_tokens = 150

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


# ── Tests ──────────────────────────────────────────────────────────────────

class TestAgentLoop:

    def _run(self, client_responses: list, conversation_id="conv-1", message="test"):
        """Run the agent loop with mocked dependencies."""
        from agent.loop import run
        from agent.db import Database

        mock_db = MagicMock(spec=Database)

        with patch("agent.loop._client") as mock_client_fn, \
             patch("agent.loop.load_conversation_for_agent", return_value=([], 0, "full")), \
             patch("agent.loop.maybe_summarise", side_effect=lambda cid, msgs, t, m: msgs), \
             patch("agent.loop.save_message"), \
             patch("agent.loop.update_conversation_title"), \
             patch("agent.tools.tool_execute_sql", return_value=("1 row", {"columns": ["n"], "rows": [[42]]}, "SELECT 1")), \
             patch("agent.tools.tool_describe_table", return_value="Schema: id BIGINT"), \
             patch("agent.tools.tool_list_tables", return_value="Available tables..."), \
             patch("agent.tools.tool_get_sample_rows", return_value=("3 rows", {"columns": ["id"], "rows": [["1"], ["2"], ["3"]]})):

            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = client_responses
            mock_client_fn.return_value = mock_client

            return run(conversation_id, message, mock_db)

    def test_respond_tool_returns_immediately(self):
        """Agent calls respond() → loop exits and returns structured payload."""
        responses = [
            _make_response(tool_calls=[
                _make_tool_call("respond", {
                    "answer": "There are 3,539 patients.",
                    "render": "text",
                    "sql": "SELECT count(*) FROM patients",
                })
            ])
        ]
        result = self._run(responses)
        assert result["answer"] == "There are 3,539 patients."
        assert result["render"] == "text"
        assert result["sql"] is not None

    def test_execute_sql_then_respond(self):
        """Agent calls execute_sql then respond — both turns complete."""
        responses = [
            _make_response(tool_calls=[_make_tool_call("execute_sql", {"sql": "SELECT count(*)"})]),
            _make_response(tool_calls=[
                _make_tool_call("respond", {"answer": "42 rows", "render": "text", "sql": "SELECT count(*)"})
            ]),
        ]
        result = self._run(responses)
        assert result["answer"] == "42 rows"

    def test_sql_failure_gets_one_retry(self):
        """First SQL error → model retries once. Second error → clarification forced."""
        with patch("agent.loop._client") as mock_client_fn, \
             patch("agent.loop.load_conversation_for_agent", return_value=([], 0, "full")), \
             patch("agent.loop.maybe_summarise", side_effect=lambda c, m, t, mode: m), \
             patch("agent.loop.save_message"), \
             patch("agent.loop.update_conversation_title"), \
             patch("agent.tools.tool_execute_sql") as mock_sql, \
             patch("agent.tools.tool_describe_table", return_value="Schema..."), \
             patch("agent.tools.tool_list_tables", return_value="Tables..."), \
             patch("agent.tools.tool_get_sample_rows", return_value=("sample", None)):

            from agent.loop import run
            from agent.db import Database

            # First two execute_sql calls fail; third call is respond
            mock_sql.side_effect = [
                ("SQL error: column not found", None, "BAD SQL"),
                ("SQL error: still broken", None, "BAD SQL 2"),
            ]

            call_num = [0]
            def side_effect_responses(*args, **kwargs):
                call_num[0] += 1
                if call_num[0] == 1:
                    return _make_response(tool_calls=[_make_tool_call("execute_sql", {"sql": "BAD SQL"})])
                if call_num[0] == 2:
                    return _make_response(tool_calls=[_make_tool_call("execute_sql", {"sql": "BAD SQL 2"})])
                return _make_response(tool_calls=[
                    _make_tool_call("respond", {
                        "answer": "Could you clarify?",
                        "render": "text",
                        "needs_clarification": True,
                    })
                ])

            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = side_effect_responses
            mock_client_fn.return_value = mock_client

            result = run("conv-1", "bad question", MagicMock(spec=Database))
            assert result["needs_clarification"] is True

    def test_max_turns_exceeded(self):
        """If the model never calls respond() within MAX_TURNS, return a graceful error."""
        from agent.loop import MAX_TURNS
        # Always return a non-respond tool call
        responses = [
            _make_response(tool_calls=[_make_tool_call("list_tables", {})])
            for _ in range(MAX_TURNS)
        ]
        result = self._run(responses)
        assert result["needs_clarification"] is True
        assert "maximum" in result["answer"].lower()

    def test_usage_is_accumulated(self):
        """Token usage should accumulate across all turns in the loop."""
        responses = [
            _make_response(tool_calls=[_make_tool_call("list_tables", {})]),
            _make_response(tool_calls=[
                _make_tool_call("respond", {"answer": "Done", "render": "text"})
            ]),
        ]
        result = self._run(responses)
        # 2 turns × 150 tokens each = 300 total
        assert result["usage"]["total_tokens"] == 300

    def test_clarification_sets_render_to_text(self):
        """When needs_clarification=True, render is always 'text'."""
        responses = [
            _make_response(tool_calls=[
                _make_tool_call("respond", {
                    "answer": "Which dataset?",
                    "render": "bar_chart",   # model tries to set chart — should be overridden
                    "needs_clarification": True,
                })
            ])
        ]
        result = self._run(responses)
        assert result["render"] == "text"

    def test_sql_sanitised_in_response(self):
        """SQL string literals must be censored before being returned."""
        responses = [
            _make_response(tool_calls=[
                _make_tool_call("respond", {
                    "answer": "Found 1 patient.",
                    "render": "text",
                    "sql": "SELECT * FROM patients WHERE first = 'John'",
                })
            ])
        ]
        result = self._run(responses)
        assert "John" not in (result["sql"] or "")
        assert "'****'" in (result["sql"] or "")
