# Agentic BI Assistant

> A natural-language business intelligence assistant for health datasets, built as the Day 5 exercise of the [Agentic AI Academy](https://www.dataroots.io) by [dataroots](https://www.dataroots.io).

## Credits

| Contribution | Credit |
|---|---|
| Exercise design, datasets, and reference materials | [dataroots](https://www.dataroots.io) — Agentic AI Academy |
| Academy instruction | Murilo Cunha — CTO at dataroots · Léa Boulos — ML Engineer at dataroots · Ali Al-Gburi — Data Consultant at dataroots |
| Productivity skills (`/grill-me` etc.) | [Matt Pocock](https://github.com/mattpocock/skills) |

---

## What it does

Ask business questions in plain English about five public health datasets stored in Azure Blob Storage — and get accurate, verifiable answers back, complete with the SQL used to derive them and rich data visualisations in the browser.

Examples:
- *"What are the top 5 conditions by patient count?"*
- *"Which diseases are most strongly associated with BRCA1?"*
- *"How many COVID-19 papers were published per year?"*

Every answer shows its source SQL. The agent asks for clarification before running a query if the question is ambiguous — it never assumes.

---

## Architecture

| Layer | Technology | Role |
|---|---|---|
| LLM | Azure OpenAI `gpt-5.4-mini` | Raw function-calling agent loop |
| Query engine | DuckDB + Azure Blob | Queries Parquet files in-place — no data movement |
| Backend | FastAPI | REST API + serves the frontend |
| Frontend | Vanilla JS + Chart.js | Chat UI with table and chart rendering |
| History | Azure PostgreSQL | Persistent conversation history with LLM summarisation |
| PII masking | Catalog-driven YAML | Masks/suppresses sensitive columns before data is returned |

**Hard constraints (per the academy brief):**
- Everything runs inside Azure — no direct calls to OpenAI, Anthropic, Gemini, etc.
- All data and resources stay in the EU.

---

## Project structure

```
exercise/
├── agent/
│   ├── db.py           DuckDB + Azure Blob connection
│   ├── masking.py      PII masking (catalog-driven) + SQL display sanitisation
│   ├── prompts.py      System prompt (7 rules) + OpenAI tool definitions
│   ├── tools.py        list_tables, describe_table, execute_sql, get_sample_rows
│   ├── history.py      PostgreSQL conversation persistence
│   ├── summarise.py    LLM-based context summarisation (triggers at 12k tokens)
│   └── loop.py         Raw function-calling agent loop (max 10 turns, 1 SQL retry)
├── api/
│   ├── main.py         FastAPI app — 4 endpoints + static frontend
│   ├── models.py       Pydantic request/response models
│   └── fingerprint.py  Machine-based user identity (no login required)
├── frontend/
│   ├── index.html      Single-page app shell
│   ├── app.js          Chat UI, Chart.js rendering, token display, session resume
│   └── style.css       Styles
├── assets/
│   ├── pii_masking.yaml          Catalog-driven PII masking rules
│   └── catalog/                  Dataset schemas and field-level descriptions
│       ├── catalog.yaml
│       └── *.guide.md
└── tests/
    ├── unit/
    │   ├── test_masking.py       29 tests — all masking styles + SQL sanitisation
    │   ├── test_tools.py         Integration tests for all 4 agent tools
    │   └── test_loop.py          7 tests — retry logic, turn cap, clarification
    └── eval/
        ├── benchmark.yaml        16 questions with gold answers across all 5 datasets
        └── runner.py             Benchmark runner (numeric + LLM-as-judge evaluation)
```

---

## Datasets

Five public synthetic health datasets, all stored as Parquet in Azure Blob (`health-open-data`):

| Dataset | Description | Schema |
|---|---|---|
| `synpuf` | ~100k synthetic Medicare beneficiaries (claims) | OMOP CDM 5.2 |
| `synthea` | ~235k simulated patients | OMOP CDM 5.2 subset |
| `coherent` | 3,539 patients with human-readable labels | Synthea-native |
| `open_targets` | Drug / target / disease associations | Open Targets Platform |
| `cord19` | ~161k COVID-19 paper metadata | Single table |

Data provided by dataroots as part of the Agentic AI Academy. See `exercise/assets/catalog/` for full schemas and field descriptions.

---

## Setup

### Prerequisites
- Python 3.12+
- Azure credentials (see below)

### Environment variables

Copy the structure below into a `.env` file at the project root — **never commit this file**:

```env
OPENAI_API_KEY=<azure-openai-key>
OPENAI_BASE_URL=https://<your-resource>.cognitiveservices.azure.com
API_VERSION=2024-12-01-preview

MODEL_NAME=gpt-5.4-mini
GPT_VERSION=2026-03-17

AZURE_STORAGE_ACCOUNT_NAME=<storage-account-name>
AZURE_STORAGE_ACCOUNT_KEY=<storage-account-key>

PG_URL=postgresql://<user>:<password>@<host>:5432/<db>?sslmode=require

EMBED_MODEL=text-embedding-3-large
EMBED_DIMENSIONS=1536
```

### Install dependencies

```bash
cd exercise
pip install -r requirements.txt
```

### Run the application

```bash
python api/main.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

---

## Testing

### Unit tests (no live connections needed)

```bash
cd exercise
python -m pytest tests/unit/ -v
```

### Benchmark / evaluation runner (requires live Azure connections)

```bash
# Full benchmark — 16 questions across all 5 datasets
python tests/eval/runner.py

# Specific questions only
python tests/eval/runner.py --ids coherent_patient_count,synthea_person_count
```

Results are saved to `tests/eval/results.json` after each run.
