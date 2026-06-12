"""PII masking and SQL display sanitisation.

Two distinct concerns:
1. apply_pii_masking()     — redacts/masks columns in query result rows based on
                             assets/pii_masking.yaml (catalog-driven, per dataset/table).
2. apply_global_pii_mask() — applies a column-name blocklist to execute_sql results
                             where the dataset/table context isn't known.
3. sanitise_sql_for_display() — replaces all SQL string literals with '****' before
                             the SQL is shown to the user in the frontend.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "assets" / "pii_masking.yaml"
_rules: dict | None = None

# Global column-name blocklist used when dataset/table context is unavailable.
_GLOBAL_PII_COLUMNS: frozenset[str] = frozenset(
    {
        "first", "last", "maiden", "ssn", "drivers", "passport",
        "address", "lat", "lon", "prefix", "suffix", "birthplace",
        "person_source_value", "provider_source_value", "npi",
    }
)


def _load_rules() -> dict:
    global _rules
    if _rules is None:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _rules = data.get("masking", {})
    return _rules


def _mask_value(value: Any, style: str, visible_chars: int = 1) -> Any:
    """Apply a single masking style to a value. Returns None for 'suppress'."""
    if value is None:
        return None
    s = str(value)
    if not s:
        return s

    if style == "redact":
        return "[REDACTED]"
    if style == "mask_all":
        return "*" * len(s)
    if style == "mask_keep_start":
        n = max(1, visible_chars)
        return s[:n] + "*" * max(0, len(s) - n)
    if style == "mask_keep_end":
        n = max(1, visible_chars)
        return "*" * max(0, len(s) - n) + s[-n:]
    if style == "mask_keep_first_half":
        half = max(1, len(s) // 2)
        return s[:half] + "*" * (len(s) - half)
    if style == "mask_email":
        if "@" not in s:
            return "*" * len(s)
        local, domain = s.split("@", 1)
        return (local[0] if local else "*") + "****@" + domain
    if style == "suppress":
        return None  # caller removes this column
    # Unknown style — fall back to full redaction
    return "[REDACTED]"


def apply_pii_masking(
    dataset: str,
    table: str,
    columns: list[str],
    rows: list[list[Any]],
) -> tuple[list[str], list[list[Any]]]:
    """Apply catalog-driven PII masking for a known dataset/table.

    Returns (new_columns, new_rows). Suppressed columns are removed entirely.
    """
    rules = _load_rules()
    table_rules: list[dict] = rules.get(dataset, {}).get(table, [])
    if not table_rules:
        return columns, rows

    col_rules: dict[str, dict] = {r["column"]: r for r in table_rules}
    suppress_cols = {c for c, r in col_rules.items() if r.get("style") == "suppress"}

    new_columns = [c for c in columns if c not in suppress_cols]
    keep_indices = [i for i, c in enumerate(columns) if c not in suppress_cols]

    new_rows = []
    for row in rows:
        new_row = []
        for i in keep_indices:
            col = columns[i]
            val = row[i] if i < len(row) else None
            if col in col_rules:
                rule = col_rules[col]
                new_row.append(_mask_value(val, rule.get("style", "redact"), rule.get("visible_chars", 1)))
            else:
                new_row.append(val)
        new_rows.append(new_row)

    return new_columns, new_rows


def apply_global_pii_mask(
    columns: list[str],
    rows: list[list[Any]],
) -> tuple[list[str], list[list[Any]]]:
    """Apply a global column-name blocklist to execute_sql results.

    Used when we cannot determine the exact dataset/table (arbitrary SQL).
    Redacts any column whose lowercase name is in the global blocklist.
    """
    needs_mask = {c for c in columns if c.lower() in _GLOBAL_PII_COLUMNS}
    if not needs_mask:
        return columns, rows

    new_rows = []
    for row in rows:
        new_row = [
            "[REDACTED]" if col in needs_mask else val
            for col, val in zip(columns, row)
        ]
        new_rows.append(new_row)
    return columns, new_rows


def sanitise_sql_for_display(sql: str) -> str:
    """Replace all single-quoted string literals in SQL with '****'.

    The logic (table names, column names, joins, filters) remains visible;
    only the literal values are hidden.
    """
    if not sql:
        return sql
    return re.sub(r"'[^']*'", "'****'", sql)
