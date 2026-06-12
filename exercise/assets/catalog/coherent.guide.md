# coherent — Synthea Coherent (Synthea-native, NOT OMOP)

A Synthea "Coherent" EHR export: 16 plain tables in Synthea's own schema. This
is the **only dataset with human-readable clinical labels** — every clinical
table carries a `description` column — so it's the go-to when a question needs
condition/medication/observation *names* rather than concept ids.

## Grain & join keys

- `patients` is the spine: one row per patient, keyed by **`id`** (3,539
  patients).
- Clinical tables (`conditions`, `medications`, `observations`, `procedures`,
  `encounters`, `immunizations`, `allergies`, `careplans`, `devices`,
  `imaging_studies`) carry:
  - `patient`  → joins to `patients.id`
  - `encounter` → joins to `encounters.id`
- ⚠ Join keys are **lowercase** (`patient`, `encounter`) — dlt normalised
  Synthea's uppercase `PATIENT`/`ENCOUNTER`. All column names here are
  lowercase.

## Codes vs. descriptions

`code` is a source code whose system depends on the table — **SNOMED**
(`conditions`, `procedures`, `allergies`), **RxNorm** (`medications`), **LOINC**
(`observations`), **CVX** (`immunizations`). `description` is the readable label;
prefer it for grouping and display.

## Dates are VARCHAR

`start`, `stop`, `date`, `birthdate`, … are strings; `CAST(... AS DATE)` for
date math.

## Hard caveats

- **Synthea-native, NOT OMOP.** Never join `coherent.*` to `synpuf.*` /
  `synthea.*` on OMOP keys — different schema, different code systems, different
  (synthetic) population.
- `supplies` is **empty (0 rows)** — also empty upstream.

## Joins

Five hub tables — **`patients`** (`id`), **`encounters`** (`id`), **`organizations`**
(`id`), **`providers`** (`id`), **`payers`** (`id`) — and every clinical/financial row
links back to them via lowercase keys (`patient`, `encounter`, `organization`,
`provider`, `payer`). Full foreign-key set (from `catalog.yaml`):

```text
allergies.patient         -> patients.id
allergies.encounter       -> encounters.id
careplans.patient         -> patients.id
careplans.encounter       -> encounters.id
conditions.patient        -> patients.id
conditions.encounter      -> encounters.id
devices.patient           -> patients.id
devices.encounter         -> encounters.id
encounters.patient        -> patients.id
encounters.organization   -> organizations.id
encounters.provider       -> providers.id
encounters.payer          -> payers.id
imaging_studies.patient   -> patients.id
imaging_studies.encounter -> encounters.id
immunizations.patient     -> patients.id
immunizations.encounter   -> encounters.id
medications.patient       -> patients.id
medications.payer         -> payers.id
medications.encounter     -> encounters.id
observations.patient      -> patients.id
observations.encounter    -> encounters.id
payer_transitions.patient -> patients.id
payer_transitions.payer   -> payers.id
procedures.patient        -> patients.id
procedures.encounter      -> encounters.id
providers.organization    -> organizations.id
supplies.patient          -> patients.id
supplies.encounter        -> encounters.id
```

### Example join — conditions by patient gender (human-readable)

```sql
SELECT pt.gender, c.description, count(*) AS n
FROM coherent.conditions c
JOIN coherent.patients pt ON pt.id = c.patient
GROUP BY pt.gender, c.description
ORDER BY n DESC
LIMIT 20;
```

## Example — top 10 conditions by patient count (human-readable)

```sql
SELECT description, count(DISTINCT patient) AS patients
FROM coherent.conditions
GROUP BY description
ORDER BY patients DESC
LIMIT 10;
```
