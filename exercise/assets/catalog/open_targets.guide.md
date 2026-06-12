# open_targets — Open Targets Platform 26.03 (NOT OMOP)

Drug-discovery data: genes/proteins (`target`), diseases (`disease`), drugs
(`drug_molecule`), and aggregated target–disease association scores
(`association_overall_indirect`). A completely different schema from the OMOP
and Synthea datasets — do not join across.

## Entities & keys

- `target` — one row per gene/protein. `id` = Ensembl gene id (e.g.
  `ENSG00000012048`), `approved_symbol` = HGNC symbol (e.g. `BRCA1`),
  `approved_name` = full name, `biotype`.
- `disease` — one row per disease/phenotype. `id` = EFO id (e.g.
  `EFO_0000305`), `name`, `description`, `therapeutic_areas` (a LIST of EFO ids).
- `drug_molecule` — one row per drug. `id` = ChEMBL id, `name`, `drug_type`,
  `maximum_clinical_stage`.
- `association_overall_indirect` — **one row per (target_id, disease_id)** with:
  `association_score` (DOUBLE, 0–1, aggregated across all evidence),
  `evidence_count`, `current_novelty`, and `timeseries` (a nested struct array —
  skip it for simple BI).

## Joins

Associations fan out to the two entity tables; `drug_molecule` self-references its
parent drug. Foreign-key set (from `catalog.yaml`):

```text
association_overall_indirect.disease_id -> disease.id
association_overall_indirect.target_id  -> target.id
drug_molecule.parent_id                 -> drug_molecule.id
```

There is **no drug column** in the association table; `drug_molecule` is a separate
entity and does not join to associations here.

## Gotchas (dlt normalised the source schema)

- The score column is **`association_score`**, not `score`; the keys are
  **`target_id` / `disease_id`** (snake_case), not `targetId`/`diseaseId`.
- Many columns are nested **LIST/STRUCT** (`parents`, `children`, `ancestors`,
  `synonyms`, `go`, `pathways`, `tractability`, `therapeutic_areas`, …). For BI,
  prefer the scalar columns (`id`, `name`, `approved_symbol`, `association_score`)
  and `UNNEST` nested ones only when needed.

## Example — diseases most associated with a target

```sql
SELECT d.name, a.association_score, a.evidence_count
FROM open_targets.association_overall_indirect a
JOIN open_targets.target  t ON t.id = a.target_id
JOIN open_targets.disease d ON d.id = a.disease_id
WHERE t.approved_symbol = 'BRCA1'
ORDER BY a.association_score DESC
LIMIT 10;
```
