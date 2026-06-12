# synpuf — OMOP CDM 5.2 (CMS DE-SynPUF, ~100k beneficiaries)

Synthetic Medicare **claims** reshaped to the OMOP Common Data Model. Safe to
query — no real patients.

## Grain & spine

- `person` is the spine: one row per beneficiary, **100,000 rows**, keyed by
  `person_id`. Every clinical event table has a `person_id` foreign key.
- Event tables (`condition_occurrence`, `drug_exposure`,
  `procedure_occurrence`, `measurement`, `observation`, `device_exposure`,
  `visit_occurrence`) are one row per event; join back to `person` on
  `person_id` and to `visit_occurrence` on `visit_occurrence_id`.
- `*_era` tables (`condition_era`, `drug_era`) are pre-aggregated spans, not raw
  events — use them for "how long on a drug/condition", not event counts.

## Unlike synthea, synpuf HAS the dimension/admin tables

`care_site`, `provider`, `location`, `death`, `device_exposure`,
`drug_strength`, `payer_plan_period` are all present here. Link via
`care_site_id`, `provider_id`, `location_id`. (`death` is sparse — 4,635 rows.)

## Concept IDs — no vocabulary loaded

`*_concept_id` columns (e.g. `condition_concept_id`, `gender_concept_id`) are
raw OMOP standard-concept **integers**. **No `concept`/vocabulary table is
loaded**, so they cannot be resolved to names inside this warehouse. The
`*_source_value` columns are mostly numeric source codes (e.g. ICD-9 as
integers), not text labels.

➡ Report the concept_id, and say the label is unresolved. For **human-readable**
condition/medication/observation names, use `coherent.*` (its `description`
column) — a different, Synthea-native cohort.

## Dates are VARCHAR

`condition_start_date`, `visit_start_date`, etc. are strings like `'2008-09-01'`.
`CAST(... AS DATE)` before any date math or ordering by time.

## Joins

Every clinical event hangs off **`person`** (`person_id`) and links to a
**`visit_occurrence`** (`visit_occurrence_id`); `person`, `visit_occurrence`, and most
event tables also carry `provider_id` → `provider` and `care_site_id` → `care_site`,
while `person`/`care_site` carry `location_id` → `location`. `drug_strength` stands
alone. Full foreign-key set (from `catalog.yaml`):

```text
care_site.location_id                          -> location.location_id
condition_era.person_id                        -> person.person_id
condition_occurrence.person_id                 -> person.person_id
condition_occurrence.provider_id               -> provider.provider_id
condition_occurrence.visit_occurrence_id       -> visit_occurrence.visit_occurrence_id
death.person_id                                -> person.person_id
device_exposure.person_id                      -> person.person_id
device_exposure.provider_id                    -> provider.provider_id
device_exposure.visit_occurrence_id            -> visit_occurrence.visit_occurrence_id
drug_era.person_id                             -> person.person_id
drug_exposure.person_id                        -> person.person_id
drug_exposure.provider_id                      -> provider.provider_id
drug_exposure.visit_occurrence_id              -> visit_occurrence.visit_occurrence_id
measurement.person_id                          -> person.person_id
measurement.provider_id                        -> provider.provider_id
measurement.visit_occurrence_id                -> visit_occurrence.visit_occurrence_id
observation.person_id                          -> person.person_id
observation.provider_id                        -> provider.provider_id
observation.visit_occurrence_id                -> visit_occurrence.visit_occurrence_id
observation_period.person_id                   -> person.person_id
payer_plan_period.person_id                    -> person.person_id
person.location_id                             -> location.location_id
person.provider_id                             -> provider.provider_id
person.care_site_id                            -> care_site.care_site_id
procedure_occurrence.person_id                 -> person.person_id
procedure_occurrence.provider_id               -> provider.provider_id
procedure_occurrence.visit_occurrence_id       -> visit_occurrence.visit_occurrence_id
provider.care_site_id                          -> care_site.care_site_id
visit_occurrence.person_id                     -> person.person_id
visit_occurrence.provider_id                   -> provider.provider_id
visit_occurrence.care_site_id                  -> care_site.care_site_id
visit_occurrence.preceding_visit_occurrence_id -> visit_occurrence.visit_occurrence_id
```

### Example join — conditions with their patient and visit

```sql
SELECT p.person_id, p.year_of_birth, v.visit_concept_id,
       co.condition_concept_id, co.condition_start_date
FROM synpuf.condition_occurrence co
JOIN synpuf.person p           ON p.person_id = co.person_id
JOIN synpuf.visit_occurrence v ON v.visit_occurrence_id = co.visit_occurrence_id
LIMIT 20;
```

## Example — top conditions by patient count

```sql
SELECT condition_concept_id, count(DISTINCT person_id) AS patients
FROM synpuf.condition_occurrence
GROUP BY condition_concept_id
ORDER BY patients DESC
LIMIT 10;
```

Results are concept_ids (integers), not names — see the concept-id caveat above.
