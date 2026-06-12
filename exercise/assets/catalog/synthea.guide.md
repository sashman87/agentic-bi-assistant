# synthea — OMOP CDM 5.2 subset (Synthea simulation)

A Synthea simulation exported to OMOP. Richer longitudinal clinical detail than
synpuf (full encounters, measurements, observations), but a **subset** of OMOP.

## Grain & spine

- `person` is the spine, keyed by `person_id`. **235,222 persons** — the
  upstream path says `synthea100k` but the bucket name is a misnomer; the row
  counts are real.
- Same event/era model as synpuf: join events to `person` on `person_id` and to
  `visit_occurrence` on `visit_occurrence_id`.
- `measurement` is **huge (~76M rows)** — always aggregate or filter; never
  `SELECT *` it unbounded.

## Missing tables (upstream does not ship them)

`care_site`, `provider`, `location`, `death`, `device_exposure`,
`drug_strength`, `payer_plan_period` are **NOT present** in synthea. The
`provider_id` / `care_site_id` columns still exist on event tables but there is
nothing to join them to here. If a question truly needs provider/care_site/death
data, that lives in `synpuf` — but `synpuf` is a **different cohort**, so never
join `synthea.person_id` to `synpuf` rows.

## Concept IDs — no vocabulary loaded

Identical to synpuf: `*_concept_id` are raw integers with **no `concept` table**
to resolve them, and `*_source_value` are mostly numeric. Report the
concept_id; for readable names use `coherent.*`.

## Dates are VARCHAR

`condition_start_date`, `visit_start_date`, `measurement_date`, … are strings.
`CAST(... AS DATE)` before date math.

## Joins

Same OMOP spine as synpuf, minus the dimension tables: events join to **`person`**
(`person_id`) and **`visit_occurrence`** (`visit_occurrence_id`). The `provider_id` /
`care_site_id` columns exist on event tables but **have no table to join to here** — so
there are no `provider`/`care_site`/`location` foreign keys. Full foreign-key set (from
`catalog.yaml`):

```text
condition_era.person_id                        -> person.person_id
condition_occurrence.person_id                 -> person.person_id
condition_occurrence.visit_occurrence_id       -> visit_occurrence.visit_occurrence_id
drug_era.person_id                             -> person.person_id
drug_exposure.person_id                        -> person.person_id
drug_exposure.visit_occurrence_id              -> visit_occurrence.visit_occurrence_id
measurement.person_id                          -> person.person_id
measurement.visit_occurrence_id                -> visit_occurrence.visit_occurrence_id
observation.person_id                          -> person.person_id
observation.visit_occurrence_id                -> visit_occurrence.visit_occurrence_id
observation_period.person_id                   -> person.person_id
procedure_occurrence.person_id                 -> person.person_id
procedure_occurrence.visit_occurrence_id       -> visit_occurrence.visit_occurrence_id
visit_occurrence.person_id                     -> person.person_id
visit_occurrence.preceding_visit_occurrence_id -> visit_occurrence.visit_occurrence_id
```

### Example join — conditions with their patient and visit

```sql
SELECT p.person_id, p.year_of_birth, v.visit_concept_id,
       co.condition_concept_id, co.condition_start_date
FROM synthea.condition_occurrence co
JOIN synthea.person p           ON p.person_id = co.person_id
JOIN synthea.visit_occurrence v ON v.visit_occurrence_id = co.visit_occurrence_id
LIMIT 20;
```

## Example — top 10 conditions by patient count

```sql
SELECT condition_concept_id, count(DISTINCT person_id) AS patients
FROM synthea.condition_occurrence
GROUP BY condition_concept_id
ORDER BY patients DESC
LIMIT 10;
```

Returns concept_ids (no names — no vocabulary table). For human-readable
condition names, query `coherent.conditions.description` instead.
