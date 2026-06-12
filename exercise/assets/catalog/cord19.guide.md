# cord19 — AllenAI CORD-19 paper metadata (NOT OMOP)

Bibliographic metadata for COVID-19 research papers. One table, `metadata`, one
row per paper (~161k). No full text and no coded clinical entities — this is
purely "papers about X", not patient data.

## Key columns

- `cord_uid` — the paper id; `title`, `abstract`, `journal`, `url`.
- `authors` — a single VARCHAR string, semicolon-separated (not a list).
- `publish_time` — a **VARCHAR** date; usually `'YYYY-MM-DD'` but sometimes only
  `'YYYY'`. Use `try_cast(publish_time AS DATE)` or `left(publish_time, 4)` for
  the year.
- Identifiers: `doi`, `pmcid`, `pubmed_id`, `arxiv_id`.

## Gotchas

- `abstract` and `journal` are often NULL — filter when counting.
- There are no foreign keys to any other dataset; cord19 stands alone.
- Free-text search is substring-based (`ILIKE '%covid%'`) — there is no
  embedding/semantic index here.

## Joins

**None.** cord19 is a single standalone table (`metadata`) with no foreign keys to any
table in any dataset — every question is answered from `metadata` alone (group,
filter, count).

## Example — papers per year

```sql
SELECT left(publish_time, 4) AS year, count(*) AS papers
FROM cord19.metadata
WHERE publish_time IS NOT NULL
GROUP BY year
ORDER BY year;
```
