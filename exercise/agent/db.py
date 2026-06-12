"""DuckDB connection wired to Azure Blob Storage.

Adapted from assets/data-explorer/server.py — same proven connection pattern,
restructured as a reusable class for the agent rather than a web server.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "dragenticaiacademy")
CONTAINER = "health-open-data"
DEFAULT_MAX_ROWS = 1_000
MAX_ROWS = 5_000
DESCRIBE_MAX = 10_000

_READ_ONLY_PREFIXES = frozenset(
    {"select", "with", "describe", "explain", "show", "pragma", "values", "table", "summarize"}
)


class QueryError(RuntimeError):
    """A SQL statement was rejected or failed to execute."""


def _json_safe(value: Any) -> Any:
    """Coerce a DuckDB cell value to something JSON-serialisable."""
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": [[_json_safe(v) for v in row] for row in self.rows],
            "row_count": self.row_count,
            "truncated": self.truncated,
        }


@dataclass
class Database:
    """A DuckDB connection scoped to the capstone's Azure Blob container."""

    connection: duckdb.DuckDBPyConnection
    container: str = CONTAINER
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _tables: dict[str, list[str]] = field(default_factory=dict, repr=False)

    @classmethod
    def connect(cls) -> "Database":
        """Open DuckDB, wire Azure credentials, discover tables, register views."""
        account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        if not account_key:
            raise RuntimeError("AZURE_STORAGE_ACCOUNT_KEY not set in .env")

        conn_str = (
            f"DefaultEndpointsProtocol=https;AccountName={ACCOUNT};"
            f"AccountKey={account_key};EndpointSuffix=core.windows.net"
        )
        con = duckdb.connect()
        con.execute("INSTALL azure; LOAD azure;")
        escaped = conn_str.replace("'", "''")
        con.execute(
            f"CREATE OR REPLACE SECRET az (TYPE azure, CONNECTION_STRING '{escaped}');"
        )
        db = cls(connection=con)
        tables = db._discover()
        db._register_views(tables)
        db._tables = tables
        return db

    def _discover(self) -> dict[str, list[str]]:
        sql = f"""
            SELECT DISTINCT
              split_part(replace(file, 'az://{self.container}/', ''), '/', 1) AS dataset,
              split_part(replace(file, 'az://{self.container}/', ''), '/', 2) AS tbl
            FROM glob('az://{self.container}/**/*.parquet')
            ORDER BY 1, 2
        """
        tables: dict[str, list[str]] = {}
        for dataset, tbl in self._raw_sql(sql, max_rows=DESCRIBE_MAX).rows:
            tables.setdefault(dataset, []).append(tbl)
        return tables

    def _register_views(self, tables: dict[str, list[str]]) -> None:
        for dataset in sorted(tables):
            self.connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{dataset}";')
            for table in tables[dataset]:
                uri = f"az://{self.container}/{dataset}/{table}/*.parquet"
                self.connection.execute(
                    f'CREATE OR REPLACE VIEW "{dataset}"."{table}" AS '
                    f"SELECT * FROM read_parquet('{uri}');"
                )

    def _raw_sql(self, sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> QueryResult:
        """Execute SQL without the read-only guard (for internal setup queries)."""
        with self._lock:
            cursor = self.connection.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            fetched = cursor.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        return QueryResult(
            columns=columns,
            rows=[tuple(row) for row in fetched[:max_rows]],
            truncated=truncated,
        )

    def run_sql(self, sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> QueryResult:
        """Execute a read-only SQL statement with the safety guard."""
        statement = sql.strip().rstrip(";").strip()
        if not statement:
            raise QueryError("Empty SQL statement.")
        if ";" in statement:
            raise QueryError("Only a single statement is allowed (no ';').")
        keyword = statement.split(None, 1)[0].lower()
        if keyword not in _READ_ONLY_PREFIXES:
            raise QueryError(
                f"Only read-only queries are allowed; '{keyword}' is not permitted."
            )
        with self._lock:
            try:
                cursor = self.connection.execute(statement)
                columns = [d[0] for d in cursor.description] if cursor.description else []
                fetched = cursor.fetchmany(max_rows + 1)
            except duckdb.Error as exc:
                raise QueryError(str(exc)) from exc
        truncated = len(fetched) > max_rows
        return QueryResult(
            columns=columns,
            rows=[tuple(row) for row in fetched[:max_rows]],
            truncated=truncated,
        )

    def describe_table(self, dataset: str, table: str) -> QueryResult:
        return self._raw_sql(
            f'DESCRIBE "{dataset}"."{table}"', max_rows=DESCRIBE_MAX
        )

    def list_tables(self) -> dict[str, list[str]]:
        return self._tables

    def sample(self, dataset: str, table: str, n: int = 10) -> QueryResult:
        return self.run_sql(
            f'SELECT * FROM "{dataset}"."{table}" LIMIT {n}', max_rows=n
        )

    def close(self) -> None:
        self.connection.close()
