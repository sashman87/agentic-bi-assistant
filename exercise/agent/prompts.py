"""System prompt and OpenAI tool definitions for the agent."""
from __future__ import annotations

SYSTEM_PROMPT = """\
You are a BI assistant for a health-data organisation. You answer business questions \
about five health datasets stored in Azure Blob Storage as Parquet files, queried via DuckDB.

## Your tools
- list_tables: See all available datasets and table names.
- describe_table(dataset, table): Get column names, types, and foreign keys. \
Call this before writing SQL so you use the correct column names.
- execute_sql(sql): Run a read-only DuckDB SQL query. Tables are accessed as \
"dataset"."table" (double-quoted identifiers). Returns columns and rows.
- get_sample_rows(dataset, table, n): Preview rows from a table. PII is automatically masked.
- respond(answer, render, sql): Submit your final answer. Always call this to finish.

## Available datasets (table-of-contents)
- synpuf: OMOP CDM 5.2 — 17 tables, ~100k synthetic Medicare beneficiaries (claims). \
Includes dimension/admin tables: care_site, provider, location, drug_strength.
- synthea: OMOP CDM 5.2 subset — 10 tables, ~235k simulated persons. \
No provider/care_site/location tables.
- coherent: Synthea-native EHR — 16 tables, 3,539 patients. \
HUMAN-READABLE labels in "description" columns. Use this when a question needs \
condition/medication/observation names rather than concept IDs.
- open_targets: Drug/target/disease — 4 tables (target, disease, drug_molecule, \
association_overall_indirect). NOT OMOP CDM.
- cord19: COVID-19 literature — 1 table (metadata), ~161k papers. Bibliographic only.

## Rules you must follow
1. If a question is ambiguous or unclear, restate your interpretation and ask the user \
to confirm before running any query. Never assume intent.
2. Every answer must reference the SQL used to derive it — pass the SQL to respond(). \
Never state a number without showing its source.
3. NEVER join coherent.* against synpuf.* or synthea.* — different schemas, \
different code systems, different synthetic populations.
4. Use coherent for human-readable names. Use synpuf/synthea for OMOP concept-ID queries.
5. If SQL fails, call describe_table to verify column names, then retry once. \
If it fails a second time, call respond() asking the user to clarify.
6. Never query more data than necessary. Use LIMIT and aggregations.
7. SQL string literal values shown to users are automatically censored — write SQL normally.
8. Always finish by calling respond() with your answer, render type, and the SQL used.\
"""

# Compact table-of-contents injected into list_tables responses.
TABLE_OF_CONTENTS: dict[str, list[str]] = {
    "synpuf": [
        "care_site", "condition_era", "condition_occurrence", "death",
        "device_exposure", "drug_era", "drug_exposure", "drug_strength",
        "location", "measurement", "observation", "observation_period",
        "payer_plan_period", "person", "procedure_occurrence", "provider",
        "visit_occurrence",
    ],
    "synthea": [
        "condition_era", "condition_occurrence", "drug_era", "drug_exposure",
        "measurement", "observation", "observation_period", "person",
        "procedure_occurrence", "visit_occurrence",
    ],
    "coherent": [
        "allergies", "careplans", "conditions", "devices", "encounters",
        "imaging_studies", "immunizations", "medications", "observations",
        "organizations", "patients", "payer_transitions", "payers",
        "procedures", "providers", "supplies",
    ],
    "open_targets": [
        "association_overall_indirect", "disease", "drug_molecule", "target",
    ],
    "cord19": ["metadata"],
}

DATASETS = list(TABLE_OF_CONTENTS.keys())

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "List all available datasets and their table names.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": (
                "Get the schema (column names, types, descriptions, foreign keys) "
                "for a specific table. Call this before writing SQL to verify column names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "string",
                        "enum": DATASETS,
                        "description": "The dataset name.",
                    },
                    "table": {
                        "type": "string",
                        "description": "The table name within the dataset.",
                    },
                },
                "required": ["dataset", "table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": (
                'Run a read-only DuckDB SQL query. Tables are accessed as "dataset"."table" '
                "(double-quoted). Returns columns and rows. Single statement only, no semicolons."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A single read-only SQL statement (SELECT, WITH, etc).",
                    },
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sample_rows",
            "description": (
                "Preview a small number of rows from a table to understand its content. "
                "PII fields are automatically masked per the masking config."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "string",
                        "enum": DATASETS,
                        "description": "The dataset name.",
                    },
                    "table": {
                        "type": "string",
                        "description": "The table name.",
                    },
                    "n": {
                        "type": "integer",
                        "description": "Number of rows to return (default 5, max 20).",
                        "default": 5,
                    },
                },
                "required": ["dataset", "table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "respond",
            "description": (
                "Submit your final answer to the user. "
                "Call this as the last step of every turn, including when asking for clarification."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "The natural language answer (or clarification question).",
                    },
                    "render": {
                        "type": "string",
                        "enum": ["text", "table", "bar_chart", "line_chart", "pie_chart"],
                        "description": (
                            "How to render the data. Use 'text' for single values or "
                            "clarification questions, 'table' for multi-column results, "
                            "'bar_chart' for ranked/categorical counts, "
                            "'line_chart' for time series, 'pie_chart' for proportions."
                        ),
                    },
                    "sql": {
                        "type": "string",
                        "description": "The SQL query used to derive the answer. Omit only for clarification questions.",
                    },
                    "needs_clarification": {
                        "type": "boolean",
                        "description": "True when asking the user to clarify rather than answering.",
                        "default": False,
                    },
                },
                "required": ["answer", "render"],
            },
        },
    },
]
