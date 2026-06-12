"""Evaluation benchmark runner.

Loads benchmark.yaml, runs each question through the agent loop, evaluates
the response using a three-tier strategy, and prints a report.

Evaluation tiers:
  1. numeric  → extract a number from the answer, compare with ±tolerance.
  2. list     → LLM-as-judge (semantic match against gold_hint).
  3. table    → check that result has rows and expected columns/keywords.
  4. clarification → check that needs_clarification=True.

Usage (from anywhere):
    python tests/eval/runner.py
    python tests/eval/runner.py --ids coherent_patient_count,cord19_total_papers
"""
from __future__ import annotations

# Ensure exercise/ is on sys.path regardless of invocation style
import sys
from pathlib import Path as _Path

_EXERCISE_ROOT = _Path(__file__).resolve().parents[2]
if str(_EXERCISE_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXERCISE_ROOT))

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

_BENCHMARK_PATH = Path(__file__).resolve().parent / "benchmark.yaml"
_RESULTS_PATH   = Path(__file__).resolve().parent / "results.json"

PASS  = "PASS"
FAIL  = "FAIL"
SKIP  = "SKIP"
ERROR = "ERROR"


# ── Helpers ────────────────────────────────────────────────────────────────

def _extract_number(text: str) -> float | None:
    """Extract the first number from a string."""
    text = text.replace(",", "")
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def _llm_judge(question: str, answer: str, gold_hint: str) -> bool:
    """Ask the LLM whether the answer addresses the question given the gold hint."""
    client = AzureOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        azure_endpoint=os.environ["OPENAI_BASE_URL"],
        api_version=os.environ.get("API_VERSION", "2024-12-01-preview"),
    )
    deployment = os.environ.get("MODEL_NAME", "gpt-5.4-mini").strip('"')
    prompt = (
        f"Question: {question}\n"
        f"Expected content: {gold_hint}\n"
        f"Agent answer: {answer}\n\n"
        "Does the agent answer adequately address the question given the expected content? "
        "Reply with exactly 'yes' or 'no', then a one-sentence reason."
    )
    resp = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=60,
    )
    verdict = resp.choices[0].message.content.strip().lower()
    return verdict.startswith("yes")


def _evaluate(q: dict, result: dict) -> tuple[str, str]:
    """Return (verdict, reason)."""
    gold_type = q.get("gold_type", "text")
    answer    = result.get("answer", "")
    data      = result.get("data")

    if gold_type == "clarification":
        if result.get("needs_clarification"):
            return PASS, "Agent correctly requested clarification."
        return FAIL, f"Expected clarification but got: {answer[:120]}"

    if gold_type == "numeric":
        gold_val  = q.get("gold_value")
        tolerance = q.get("tolerance", 0.01)
        extracted = _extract_number(answer)
        if gold_val is not None and extracted is not None:
            delta = abs(extracted - gold_val) / max(abs(gold_val), 1)
            if delta <= tolerance:
                return PASS, f"Got {extracted:,.0f} (expected {gold_val:,.0f}, Δ={delta:.1%})"
            return FAIL, f"Got {extracted:,.0f}, expected {gold_val:,.0f} (Δ={delta:.1%} > {tolerance:.1%})"
        if gold_val is None:
            # gold_hint only — fall through to LLM judge
            gold_type = "list"
        else:
            return FAIL, f"Could not extract number from: {answer[:120]}"

    if gold_type in ("list", "table"):
        gold_hint = q.get("gold_hint", "")
        try:
            passed = _llm_judge(q["question"], answer, gold_hint)
            return (PASS if passed else FAIL), ("LLM judge: yes" if passed else "LLM judge: no")
        except Exception as exc:
            return ERROR, f"LLM judge failed: {exc}"

    return SKIP, "Unknown gold_type"


# ── Runner ─────────────────────────────────────────────────────────────────

def run_benchmark(filter_ids: list[str] | None = None) -> None:
    from agent.db import Database
    from agent.history import create_conversation, init_db
    from agent import loop as agent_loop

    data   = yaml.safe_load(_BENCHMARK_PATH.read_text(encoding="utf-8"))
    questions = data["questions"]

    if filter_ids:
        questions = [q for q in questions if q["id"] in filter_ids]

    print(f"\n{'─'*60}")
    print(f"  Agentic BI Benchmark  ({len(questions)} questions)")
    print(f"{'─'*60}\n")

    print("Connecting to Azure Blob / DuckDB …")
    db = Database.connect()
    init_db()

    results = []
    passed = failed = errors = skipped = 0

    for q in questions:
        qid  = q["id"]
        text = q["question"]
        print(f"  [{qid}] {text[:70]}")
        t0 = time.time()

        try:
            # Each question gets its own throwaway conversation
            conv_id = create_conversation("eval-runner", title=qid)
            result  = agent_loop.run(conv_id, text, db)
            verdict, reason = _evaluate(q, result)
        except Exception as exc:
            verdict, reason = ERROR, str(exc)
            result = {}

        elapsed = time.time() - t0

        color = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭ ", "ERROR": "💥"}[verdict]
        print(f"    {color} {verdict}  ({elapsed:.1f}s)  {reason}")
        if verdict == FAIL and result.get("answer"):
            print(f"       Answer: {result['answer'][:120]}")
        if result.get("sql"):
            print(f"       SQL:    {result['sql'][:100]}")

        if   verdict == PASS:  passed  += 1
        elif verdict == FAIL:  failed  += 1
        elif verdict == ERROR: errors  += 1
        else:                  skipped += 1

        usage = result.get("usage", {})
        results.append({
            "id":       qid,
            "question": text,
            "verdict":  verdict,
            "reason":   reason,
            "answer":   result.get("answer", ""),
            "sql":      result.get("sql", ""),
            "elapsed":  round(elapsed, 2),
            "tokens":   usage.get("total_tokens", 0),
        })

    db.close()

    total = len(questions)
    print(f"\n{'─'*60}")
    print(f"  Results: {passed}/{total} passed  |  {failed} failed  |  {errors} errors  |  {skipped} skipped")
    print(f"{'─'*60}\n")

    _RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Full results saved to {_RESULTS_PATH}\n")

    if failed or errors:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the BI agent benchmark.")
    parser.add_argument("--ids", help="Comma-separated list of question IDs to run")
    args = parser.parse_args()
    filter_ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    run_benchmark(filter_ids)
