# Gold to Chunk Pipeline Documentation

## Scope

This file documents the end to end path from Gold datasets to Knowledge, then Knowledge to Chunks.


## Outputs of this stage

1. knowledge/gold_knowledge_assets (Delta)
2. knowledge/gold_knowledge_chunks (Delta)

---

## Gold Data Layout

**Container:** gold-genai

Folders are separated by business domain for access control, lineage, and downstream filtering.

- incidents/gold_incidents.csv
- quality/gold_quality_metrics.csv
- maintenance/gold_equipment_maintenance.csv
- production/gold_production_metrics.csv
- sop/gold_sop_documents.csv

---

## Access Model and Immutability of Gold

### Goal

Gold data is treated as immutable input.
If code tries to write to Gold, it must fail at the storage layer.

### Authentication Approaches Evaluated

#### Option A: Access Connector with Managed Identity

**Reason for trying it:**
No secrets to manage and Azure manages credentials.

**Reason it failed in this workspace:**
The Databricks workspace tier and configuration did not support Managed Identity at runtime, so Spark could not resolve MSI tenant context.

#### Option B: Service Principal with Azure Key Vault and OAuth

**Reason for switching:**
It works reliably in Standard and Hybrid workspaces.
Secrets are stored in Key Vault, not in notebooks.

### Access Enforcement

**Control plane:**
Azure RBAC grants the identity permission at the storage account or container scope.

**Data plane:**
ADLS Gen2 ACLs grant read and execute for folder traversal.

**Key point:**
RBAC alone is not enough for ADLS Gen2. ACLs must allow traversal.

---

## Post Gold Validation Gates

These gates run before any Knowledge transformation.

### Gate 1: Path and permissions

Read Gold files using ABFSS paths, not HTTPS blob paths.
Confirm access by reading a small sample with Spark.

### Gate 2: Schema readiness

Run printSchema on each Gold DataFrame.
Confirm required fields exist for narrative construction and metadata.

### Gate 3: Completeness

Run count on each dataset to confirm full read and no partial ingestion.

### Gate 4: Human readability

Use show(truncate=False) to confirm the rows contain meaningful text fields, not codes or placeholders.

**Reason:**
If humans cannot read it, embeddings will be low quality.

---

## Knowledge Layer

### Definition

Knowledge is a semantic representation built for LLM reasoning and retrieval, not for SQL analytics.

### Why a unified Knowledge table exists

Multiple Gold datasets are normalized into one contract so that downstream systems do not need dataset specific logic.
Separation is preserved using knowledge_type, business_domain, metadata, and source_reference.

### Knowledge Contract

The Knowledge table schema is defined explicitly and created as an empty Delta table before writing data.
This prevents schema drift and forces every producer to conform.

### Knowledge Schema Fields

**knowledge_id:**
Purpose: unique identifier for lineage, dedup, and join keys into other layers.

**knowledge_type:**
Purpose: classifies the row for chunking and retrieval logic.

**business_domain:**
Purpose: business friendly grouping for access control and scoping.

**content_text:**
Purpose: the narrative text that later becomes the primary embedding input.

**source_reference:**
Purpose: stable reference for grounding and citations later.

**event_date:**
Purpose: time scoping, recency filters, and time aware Q and A.

**metadata:**
Purpose: filtering without polluting content_text.

### Knowledge Contract Creation

**Delta path:**
abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_assets

**Creation behavior:**
Create empty DataFrame with the contract schema, then write overwrite mode to initialize the Delta log.

---

## Gold to Knowledge Transformation Rules

### Global rules applied across datasets

- Do not drop rows silently.
- Do not mix low signal metadata fields into content_text.
- Keep metadata as a map of key value pairs.
- Derive event_date from the appropriate date field per dataset.
- Set knowledge_type deterministically per dataset.
- Set business_domain deterministically per dataset.

### Incidents to Knowledge

**Source:**
incidents/gold_incidents.csv

**Narrative composition:**
content_text is built using concat_ws over the incident fields.
The sentence includes incident_date, equipment, type, line_id, failure type, category, root cause, downtime, resolution, and severity.

**event_date:**
Derived using to_date(incident_date).

**metadata:**
Captured as create_map of shift, reported_by, verified_by, environmental_temp_c, humidity_percent, production_impact_units, labor_hours, parts_cost_usd, mttr_minutes, mtbf_hours.

**knowledge_id:**
Generated using uuid().

**knowledge_type:**
Set to incident.

**business_domain:**
Set to operations.

**source_reference:**
Mapped from incident_id.

#### Incidents post transform validations

**Null critical fields check:**
Count rows where knowledge_id, knowledge_type, business_domain, or content_text are null.

**Metadata non empty check:**
Count rows where metadata is null or size(metadata) equals 0.

**Write behavior:**
Append to the Knowledge Delta path.

### Quality to Knowledge

**Source:**
quality/gold_quality_metrics.csv

**Key difference:**
knowledge_id is taken from metric_id instead of generating uuid.
This keeps direct lineage to quality metrics.

**Narrative composition:**
content_text describes inspection_date, product_name, product_sku, line_id, defect type and category, defect_count, total_inspected, defect_rate_percent, inspection_stage, corrective_action.

**event_date:**
Derived using to_date(inspection_date).

**metadata:**
Captured as create_map including product_sku, batch_id, inspection_stage, defect_type, defect_category, defect_rate_percent, defect_rate_ppm, specification_limit_percent, specification_type, inspector_name, measurement_tool, cost_impact_usd, rework_hours, scrap_count, shift, temperature_c, humidity_percent, line_id, equipment_id.

**knowledge_type:**
Set to quality.

**business_domain:**
Set to quality.

**source_reference:**
Built as concat_ws(' | ', 'quality', metric_id).

**Write behavior:**
Append to the Knowledge Delta path.

### Maintenance to Knowledge

**Source:**
maintenance/gold_equipment_maintenance.csv

**Narrative composition:**
content_text includes maintenance_date, maintenance_type, equipment_name and equipment_id, line_id, maintenance_category, failure_mode, work_performed, equipment_status.

**event_date:**
Derived using to_date(maintenance_date).

**knowledge_id:**
Taken from maintenance_id.

**knowledge_type:**
Set to maintenance.

**business_domain:**
Set to manufacturing_operations.

**source_reference:**
Set to gold_equipment_maintenance.csv.

**metadata:**
Captured as create_map including maintenance_type, maintenance_category, technician_name, certification_level, duration_hours, total_cost_usd, downtime_impact, work_priority, equipment_status.

**Write behavior:**
Append to the Knowledge Delta path.

### Production to Knowledge

**Source:**
production/gold_production_metrics.csv

**Narrative composition:**
content_text includes shift_date, shift, line_id, oee_percent vs target_oee_percent, produced units, good_units, defect_units, downtime_min, performance_percent, quality_percent, and notes.

**knowledge_id:**
Taken from metric_id.

**knowledge_type:**
Set to production.

**business_domain:**
Set to manufacturing_operations.

**event_date:**
Derived using to_date(shift_date).

**metadata:**
Captured as create_map including line_id, shift, planned_production_time_min, downtime_min, operating_time_min, total_units_produced, good_units, defect_units, availability_percent, performance_percent, quality_percent, oee_percent, target_oee_percent, equipment_ids_used, crew_size, shift_supervisor.

**Write behavior:**
Append to the Knowledge Delta path.

### SOP to Knowledge

**Source:**
sop/gold_sop_documents.csv

**Narrative composition:**
content_text is built as a single narrative describing SOP id, document title, applicable equipment, and procedure details from the SOP content_text.

**knowledge_id:**
Taken from sop_id.

**knowledge_type:**
Set to sop.

**business_domain:**
Set to manufacturing_operations.

**source_reference:**
Set to gold_sop_documents.csv.

**event_date:**
Taken from effective_date.

**metadata:**
Captured as create_map including sop_id, document_title, document_type, equipment_id, equipment_name, version, effective_date, review_date, author, approver, regulatory_reference, page_count, word_count, last_updated.

**Write behavior:**
Append to the Knowledge Delta path.

---

## Knowledge Wide Checks Before Chunking

These checks run after all datasets have been appended.

### Check 1: contract columns exist and types are stable

Required: knowledge_id, knowledge_type, business_domain, content_text, source_reference, event_date, metadata.

### Check 2: dataset scale

Use count to confirm total Knowledge rows.
This project observed hundreds of rows, which is small but valid for demonstrating production contracts and validation gates.

### Check 3: knowledge_type distribution

Group by knowledge_type and count to see domain coverage.

**Important observation from the notes:**
A portion of rows had knowledge_type as NULL.

**Interpretation:**
These rows still had quality like inspection content, so the issue is classification loss, not missing content.

---

## Chunking Layer

Chunking is not just splitting text.
Chunking is defining the LLM reasoning unit and sealing it behind a contract.

### Why the chunk table exists even when many rows are not split

- It allows independent lifecycle of chunking and embeddings.
- It provides chunk level lineage and citation keys.
- It supports re chunking and re embedding without rewriting source knowledge.
- It provides strict gating so only chunk approved rows can reach vector indexing.

### Chunk Contract

**Delta path:**
abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_chunks/

**Creation behavior:**
Create an empty Delta table with an explicit chunk_schema.

### Chunk Schema Fields

**knowledge_chunk_id:**
Purpose: unique id per chunk for vector indexing and citations.

**knowledge_id:**
Purpose: lineage back to the Knowledge row.

**knowledge_type_original:**
Purpose: raw type from Knowledge.

**knowledge_type_effective:**
Purpose: the normalized type used by chunk logic.

**chunk_index:**
Purpose: ordering inside a knowledge_id when splitting occurs.

**chunk_text:**
Purpose: exact text unit that will be embedded later.

**chunk_token_count:**
Purpose: approximate token size for budget control.


## Knowledge Type Resolution

The chunking code derives knowledge_type_effective from the Knowledge table.

**Rule used in code:**
If knowledge_type is null, set knowledge_type_effective to QUALITY.
Otherwise, set knowledge_type_effective to lower(trim(knowledge_type)).

**reality check on this rule:**
This mixes casing: null types become QUALITY while non null types become lowercase.
That inconsistency can break downstream filters that expect one casing.


---

## Chunk Eligibility Validation

It rejects placeholders but allows short high signal texts.

### Placeholder rejection rule

- Reject when content_text is null or empty.
- Reject when content_text matches common placeholders: n/a, na, none, tbd, all good, no issues, ok, passed.

### Semantic signal rules

**Action or event signal:**
Detects operational verbs and events in content_text.
Examples: shutdown, failure, alarm, trip, leak, replaced, calibrated, lubricated, repaired, inspection failed, defect, exceeded, warning, must, do not, before, after, stopped.

**Numeric signal:**
Detects numbers with units and percentages.
Pattern includes: %, ppm, usd, hours, hrs, minutes, min, °c, bar, rpm.

**Outcome signal:**
Detects explicit outcomes such as initiated, completed, failed, triggered, stopped, started, replaced.

### Short low signal rejection rule

Reject when length(content_text) is less than 120 characters and none of the three signals are present.

**Exception:**
Do not apply this short rule to sop and maintenance types.

### Validation output

The validated_knowledge DataFrame adds validation_status with APPROVED or REJECTED.
Approved rows move forward to chunk generation.

---

## Chunk Generation Strategies Implemented

### Strategy A: one row equals one chunk for incident and production

For knowledge_type_effective in incident and production:

- Set chunk_index to 0.
- Rename content_text to chunk_text.
- Keep business_domain, equipment_id, line_id, event_date, source_reference.
- Add knowledge_chunk_id as uuid().
- Add created_at as current_timestamp().
- Compute chunk_token_count as length(normalized_whitespace(chunk_text)) divided by 4.

**Note:**
This is a heuristic token estimate, not a real tokenizer.

### Strategy B: SOP and maintenance section splitting

- Filter rows where knowledge_type_effective is sop or maintenance.
- Split content_text into sections using SECTION_REGEX delimiters.
- Use posexplode to generate chunk_index and chunk_text.
- Trim chunk_text and drop empty sections.
- Compute chunk_token_count using the same length divided by 4 heuristic.
- Add knowledge_chunk_id and created_at.

### Additional SOP splitting logic

A Python UDF split_sop_sections is defined using regex rules and a buffer to keep each chunk under a character target.
This is applied to sop_df and then exploded into chunk_text.
The UDF based splitting is used again on sop_chunks_df to split already produced SOP chunks further.

### Normalization and union

- incident_prod_chunks_norm contains the incident and production chunks with the normalized column set.
- maintenance_chunks_norm contains maintenance chunks with normalized column set.
- sop_split_chunks_norm contains SOP split chunks with normalized column set.
- all_chunks is a unionByName of those three DataFrames.

**reality check on coverage:**
Quality chunks are not included in the union in this notebook.
If we claim the system covers quality, the code in this file does not prove it.

**Fix:**
Add quality to the single chunk path or create a quality specific split path and include it in all_chunks.

---

## Chunk Table Writes

The chunk table is initialized by overwriting an empty Delta table at the chunk path.
This notebook appends incident_prod_chunks to the chunk path.
It does not write the final all_chunks union back to storage in the provided cells.
If all_chunks is intended to be authoritative, add an explicit write step for it.

---

## Chunk Validations After Generation

- **Check 1:** chunk_text is not null and length is at least 40 characters.
- **Check 2:** knowledge_chunk_id is not null.
- **Check 3:** knowledge_chunk_id uniqueness by comparing total count and distinct count.
- **Check 4:** token count distribution per knowledge_type_effective using min, p50, max.

---

## Operational Assumptions and Tradeoffs

**Token count is heuristic.**
- Pros: fast, deterministic, no external dependency.
- Cons: inaccurate budgeting vs real model tokenizers.

**Regex based splitting is deterministic.**
- Pros: predictable sections and stable chunk_index.
- Cons: SOP formats that do not match delimiters will produce poor splits.

**Python UDF splitting is flexible.**
- Pros: custom chunk sizing.
- Cons: UDFs are slower and harder to scale than native Spark functions.

---

## What to Improve Before Calling This Production Grade

1. Normalize knowledge_type_effective casing to one convention.
2. Ensure quality data is chunked and written.
3. Replace token heuristic with a real tokenizer in an offline step if budgets matter.
4. Replace Python UDF splitting with native Spark when scale increases.
5. Add a single authoritative write of all_chunks to the chunk Delta path.

---

## Reproducibility

All data paths are deterministic ABFSS paths.
All ids are generated using uuid(), which is unique but not stable between re runs.

**idempotency:**
Use deterministic chunk ids derived from knowledge_id plus chunk_index and a hash of chunk_text.

---

## Quick Run Order for This Stage

1. Create knowledge contract table.
2. Append incidents, quality, maintenance, production, and SOP into knowledge assets.
3. Read knowledge assets and validate.
4. Create chunk contract table.
5. Generate chunks with validation gates.
6. Run chunk table integrity checks.