"""Unit tests for agent/tools.py.

Most tool functions require a live Database connection (integration-style).
The pure helper tool_list_tables() can be tested without one.
DB-dependent tests are marked with @pytest.mark.integration and skipped
unless the AZURE_STORAGE_ACCOUNT_KEY environment variable is set.
"""
from __future__ import annotations

import os
import pytest

from agent.tools import tool_list_tables, tool_describe_table, tool_execute_sql, tool_get_sample_rows
from agent.prompts import TABLE_OF_CONTENTS

_LIVE = bool(os.getenv("AZURE_STORAGE_ACCOUNT_KEY"))


# ── tool_list_tables (no DB needed) ───────────────────────────────────────

class TestToolListTables:
    def test_returns_string(self):
        result = tool_list_tables()
        assert isinstance(result, str)

    def test_contains_all_datasets(self):
        result = tool_list_tables()
        for ds in TABLE_OF_CONTENTS:
            assert ds in result

    def test_contains_table_counts(self):
        result = tool_list_tables()
        for ds, tables in TABLE_OF_CONTENTS.items():
            assert str(len(tables)) in result


# ── DB-dependent tools ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db():
    if not _LIVE:
        pytest.skip("AZURE_STORAGE_ACCOUNT_KEY not set — skipping integration tests")
    from agent.db import Database
    conn = Database.connect()
    yield conn
    conn.close()


@pytest.mark.integration
class TestToolDescribeTable:
    def test_coherent_patients_returns_schema(self, db):
        result = tool_describe_table(db, "coherent", "patients")
        assert "patients" in result.lower()
        assert "id" in result.lower()

    def test_unknown_table_returns_error(self, db):
        result = tool_describe_table(db, "coherent", "nonexistent_table")
        assert "error" in result.lower()


@pytest.mark.integration
class TestToolExecuteSql:
    def test_count_coherent_patients(self, db):
        sql = 'SELECT count(*) AS n FROM "coherent"."patients"'
        result_str, data, sql_out = tool_execute_sql(db, sql)
        assert data is not None
        assert data["row_count"] == 1
        count = data["rows"][0][0]
        assert int(count) == 3539

    def test_invalid_sql_returns_error(self, db):
        result_str, data, _ = tool_execute_sql(db, "SELECT * FROM nonexistent.table")
        assert data is None
        assert "SQL error" in result_str

    def test_write_sql_rejected(self, db):
        result_str, data, _ = tool_execute_sql(db, "DROP TABLE coherent.patients")
        assert data is None
        assert "SQL error" in result_str or "not permitted" in result_str

    def test_pii_columns_masked(self, db):
        sql = 'SELECT id, first, last FROM "coherent"."patients" LIMIT 3'
        result_str, data, _ = tool_execute_sql(db, sql)
        if data:
            cols = data["columns"]
            rows = data["rows"]
            if "first" in cols:
                idx = cols.index("first")
                for row in rows:
                    val = row[idx]
                    assert val == "[REDACTED]" or (len(val) > 1 and "*" in val)


@pytest.mark.integration
class TestToolGetSampleRows:
    def test_returns_rows(self, db):
        result_str, data = tool_get_sample_rows(db, "coherent", "patients", 3)
        assert data is not None
        assert len(data["rows"]) == 3

    def test_lat_lon_suppressed(self, db):
        _, data = tool_get_sample_rows(db, "coherent", "patients", 5)
        assert data is not None
        assert "lat" not in data["columns"]
        assert "lon" not in data["columns"]

    def test_first_name_masked(self, db):
        _, data = tool_get_sample_rows(db, "coherent", "patients", 5)
        assert data is not None
        if "first" in data["columns"]:
            idx = data["columns"].index("first")
            for row in data["rows"]:
                val = str(row[idx])
                assert len(val) <= 2 or "*" in val, f"first name not masked: {val}"

    def test_n_capped_at_20(self, db):
        _, data = tool_get_sample_rows(db, "coherent", "patients", 999)
        assert data is not None
        assert len(data["rows"]) <= 20
