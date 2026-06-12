"""Unit tests for agent/masking.py — every masking style and SQL sanitisation."""
from __future__ import annotations

import pytest

# We test the internal _mask_value and public apply_pii_masking / sanitise_sql_for_display.
from agent.masking import (
    _mask_value,
    apply_global_pii_mask,
    apply_pii_masking,
    sanitise_sql_for_display,
)


# ── _mask_value ────────────────────────────────────────────────────────────

class TestMaskValue:
    def test_redact(self):
        assert _mask_value("John Smith", "redact") == "[REDACTED]"

    def test_mask_all(self):
        assert _mask_value("John", "mask_all") == "****"

    def test_mask_keep_start_default(self):
        assert _mask_value("Jonathan", "mask_keep_start", 1) == "J*******"

    def test_mask_keep_start_two_chars(self):
        assert _mask_value("Jonathan", "mask_keep_start", 2) == "Jo******"

    def test_mask_keep_start_shorter_than_visible(self):
        assert _mask_value("Jo", "mask_keep_start", 5) == "Jo"

    def test_mask_keep_end(self):
        assert _mask_value("123-45-6789", "mask_keep_end", 4) == "*******6789"

    def test_mask_keep_first_half_even(self):
        # "Jonathan" = 8 chars → half = 4 → keep first 4 = "Jona"
        val = _mask_value("Jonathan", "mask_keep_first_half")
        assert val == "Jona****"

    def test_mask_keep_first_half_odd(self):
        # "Hello" length 5 → half=2 → "He***"
        val = _mask_value("Hello", "mask_keep_first_half")
        assert val == "He***"

    def test_mask_email_standard(self):
        assert _mask_value("john.doe@gmail.com", "mask_email") == "j****@gmail.com"

    def test_mask_email_no_at_sign(self):
        result = _mask_value("notanemail", "mask_email")
        assert result == "**********"

    def test_suppress_returns_none(self):
        assert _mask_value("52.3701", "suppress") is None

    def test_none_input(self):
        assert _mask_value(None, "redact") is None

    def test_empty_string(self):
        assert _mask_value("", "mask_all") == ""

    def test_unknown_style_falls_back_to_redact(self):
        assert _mask_value("secret", "blorp") == "[REDACTED]"


# ── apply_pii_masking ──────────────────────────────────────────────────────

class TestApplyPiiMasking:
    """Tests against the rules in assets/pii_masking.yaml."""

    def _run(self, dataset, table, columns, rows):
        return apply_pii_masking(dataset, table, columns, rows)

    def test_no_rules_passthrough(self):
        cols = ["id", "condition"]
        rows = [["abc", "Hypertension"]]
        out_cols, out_rows = self._run("coherent", "conditions", cols, rows)
        assert out_cols == cols
        assert out_rows == rows

    def test_coherent_patients_first_masked(self):
        cols = ["id", "first", "last"]
        rows = [["abc123", "Jonathan", "Smith"]]
        out_cols, out_rows = self._run("coherent", "patients", cols, rows)
        assert "first" in out_cols
        assert out_rows[0][out_cols.index("first")] == "J*******"

    def test_coherent_patients_ssn_masked_keep_end(self):
        cols = ["id", "ssn"]
        rows = [["abc123", "123-45-6789"]]
        out_cols, out_rows = self._run("coherent", "patients", cols, rows)
        masked = out_rows[0][out_cols.index("ssn")]
        assert masked.endswith("6789")
        assert "*" in masked

    def test_coherent_patients_lat_suppressed(self):
        cols = ["id", "first", "lat", "lon"]
        rows = [["abc123", "Jane", "51.5074", "-0.1278"]]
        out_cols, out_rows = self._run("coherent", "patients", cols, rows)
        assert "lat" not in out_cols
        assert "lon" not in out_cols
        assert "id" in out_cols

    def test_coherent_patients_address_redacted(self):
        cols = ["id", "address"]
        rows = [["abc123", "123 Main Street, London"]]
        out_cols, out_rows = self._run("coherent", "patients", cols, rows)
        assert out_rows[0][out_cols.index("address")] == "[REDACTED]"

    def test_multiple_rows(self):
        cols = ["id", "first", "last"]
        rows = [["1", "Alice", "Walker"], ["2", "Bob", "Jones"]]
        _, out_rows = self._run("coherent", "patients", cols, rows)
        assert out_rows[0][1] == "A****"
        assert out_rows[1][1] == "B**"


# ── apply_global_pii_mask ──────────────────────────────────────────────────

class TestApplyGlobalPiiMask:
    def test_blocks_ssn(self):
        cols = ["id", "ssn", "age"]
        rows = [["1", "123-45-6789", 42]]
        out_cols, out_rows = apply_global_pii_mask(cols, rows)
        assert out_rows[0][1] == "[REDACTED]"
        assert out_rows[0][2] == 42

    def test_passthrough_unknown_columns(self):
        cols = ["disease_name", "score"]
        rows = [["Diabetes", 0.87]]
        out_cols, out_rows = apply_global_pii_mask(cols, rows)
        assert out_rows == rows

    def test_case_insensitive(self):
        cols = ["SSN", "First", "LAST"]
        rows = [["123", "Jane", "Doe"]]
        _, out_rows = apply_global_pii_mask(cols, rows)
        assert all(v == "[REDACTED]" for v in out_rows[0])


# ── sanitise_sql_for_display ───────────────────────────────────────────────

class TestSanitiseSqlForDisplay:
    def test_single_literal(self):
        sql = "SELECT * FROM patients WHERE first = 'John'"
        result = sanitise_sql_for_display(sql)
        assert "'****'" in result
        assert "John" not in result

    def test_multiple_literals(self):
        sql = "SELECT * FROM p WHERE first = 'Jane' AND city = 'London'"
        result = sanitise_sql_for_display(sql)
        assert result.count("'****'") == 2

    def test_no_literals_unchanged(self):
        sql = "SELECT count(*) FROM patients"
        assert sanitise_sql_for_display(sql) == sql

    def test_empty_literal(self):
        sql = "SELECT * FROM p WHERE name = ''"
        result = sanitise_sql_for_display(sql)
        assert "'****'" in result

    def test_none_safe(self):
        assert sanitise_sql_for_display(None) is None

    def test_empty_string_safe(self):
        assert sanitise_sql_for_display("") == ""
