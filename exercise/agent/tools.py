"""Tool implementations called by the agent loop.

Each tool_* function maps 1-to-1 with an entry in prompts.TOOLS.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .db import Database, QueryError
from .masking import apply_global_pii_mask, apply_pii_masking
from .prompts import TABLE_OF_CONTENTS

_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "catalog" / "catalog.yaml"
)
_catalog_cache: dict | None = None


def _load_catalog() -> dict:
    global _catalog_cache
    if _catalog_cache is None:
        with open(_CATALOG_PATH, encoding="utf-8") as f:
            _catalog_cache = yaml.safe_load(f)
    return _catalog_cache


# ---------------------------------------------------------------------------
# Tool: list_tables
# ---------------------------------------------------------------------------

def tool_list_tables() -> str:
    lines = ["Available datasets and tables:\n"]
    for dataset, tables in TABLE_OF_CONTENTS.items():
        lines.append(f"**{dataset}** ({len(tables)} tables): {', '.join(tables)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: describe_table
# ---------------------------------------------------------------------------

def tool_describe_table(db: Database, dataset: str, table: str) -> str:
    try:
        result = db.describe_table(dataset, table)
    except Exception as exc:
        return f"Error describing {dataset}.{table}: {exc}"

    # Pull descriptions and FK references from catalog.yaml
    catalog = _load_catalog()
    col_meta: dict[str, dict] = {}
    for ds in catalog.get("datasets", []):
        if ds["name"] == dataset:
            for tbl in ds.get("tables", []):
                if tbl["name"] == table:
                    for col in tbl.get("columns", []):
                        col_meta[col["name"]] = {
                            "description": col.get("description") or "",
                            "references": col.get("references") or "",
                        }
                    break
            break

    lines = [f"Schema for {dataset}.{table}:\n"]
    lines.append(f"{'Column':<38} {'Type':<18} Description / FK")
    lines.append("-" * 90)
    for row in result.rows:
        name, dtype = row[0], row[1]
        meta = col_meta.get(name, {})
        desc = meta.get("description", "")
        ref = meta.get("references", "")
        ref_str = f"  → {ref}" if ref else ""
        lines.append(f"{name:<38} {dtype:<18} {desc}{ref_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: execute_sql
# ---------------------------------------------------------------------------

def tool_execute_sql(
    db: Database, sql: str
) -> tuple[str, dict[str, Any] | None, str]:
    """Execute SQL. Returns (summary_str, data_dict_or_None, sql_used)."""
    try:
        result = db.run_sql(sql)
    except QueryError as exc:
        return f"SQL error: {exc}", None, sql

    columns = result.columns
    rows = [list(r) for r in result.rows]

    # Apply global PII mask (best-effort when dataset/table context is unknown)
    columns, rows = apply_global_pii_mask(columns, rows)

    data: dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
    }

    summary = f"Query returned {result.row_count} row(s)"
    if result.truncated:
        summary += " (truncated to limit)"
    summary += f".\nColumns: {', '.join(columns)}"
    if rows:
        preview = rows[:3]
        summary += f"\nFirst {len(preview)} row(s): {json.dumps([[str(v) for v in r] for r in preview], default=str)}"
    return summary, data, sql


# ---------------------------------------------------------------------------
# Tool: get_sample_rows
# ---------------------------------------------------------------------------

def tool_get_sample_rows(
    db: Database, dataset: str, table: str, n: int = 5
) -> tuple[str, dict[str, Any] | None]:
    """Sample rows with full catalog-driven PII masking applied."""
    n = min(max(1, n), 20)
    try:
        result = db.sample(dataset, table, n)
    except Exception as exc:
        return f"Error sampling {dataset}.{table}: {exc}", None

    columns, rows = apply_pii_masking(
        dataset, table, result.columns, [list(r) for r in result.rows]
    )

    data: dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }
    summary = f"Sample of {len(rows)} rows from {dataset}.{table}.\nColumns: {', '.join(columns)}"
    if rows:
        summary += (
            f"\nFirst row: {json.dumps([str(v) for v in rows[0]], default=str)}"
        )
    return summary, data
