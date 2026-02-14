# Chunk to Embeddings Pipeline Documentation

## Scope

This document covers the complete transition from the chunking layer to the embeddings layer.

It defines all preconditions, validation gates, corruption handling, quarantine logic, embedding contracts, idempotent execution rules, batching policies, retry policies, schema guarantees, run success criteria, and run metrics.

### This stage produces:

- embedding-ready dataset (semantic v2)
- quarantine dataset for corrupted chunks
- embeddings Delta table with vector payload
- run-level metrics for monitoring


---

## Preconditions Before Embeddings

Before any embedding API call is allowed, the following checks were executed on gold_knowledge_chunks_v1.

### 1.1 Table Readability

- gold_knowledge_chunks_v1 is readable as Delta.
- _delta_log exists and history is queryable.
- Record count matches post-chunk validation stage.

### 1.2 Identity Stability

- knowledge_chunk_id is NOT NULL.
- knowledge_id is NOT NULL.
- total rows == distinct(knowledge_chunk_id).
- No duplicate chunk IDs.

### 1.3 Text Cleanliness

- chunk_text is NOT NULL.
- length(trim(chunk_text)) >= 40.
- No placeholder-only rows.
- No whitespace-only rows.

### 1.4 Token Sanity

- chunk_token_count > 0.
- No chunk exceeds hard token limits per knowledge type.
- Distribution inspected by knowledge_type_effective.

If any of the above failed, embedding stage was blocked.

---

## Corruption Detection

During pre-embedding validation, 3 major corruption patterns were identified.

### 2.1 Corrupted Natural Language

**Observed issue:**

chunk_text beginning with malformed date patterns such as:
- "On 125 ,"
- "On 2.0 ,"
- "On 5.0 ,"

**Detection rule:**

- event_date IS NULL
- AND chunk_text matches malformed numeric date prefix

### 2.2 Missing event_date

**Observed issue:**

event_date IS NULL for types that require it:
- incident
- maintenance
- production

**Detection rule:**

- event_date IS NULL
- knowledge_type_effective IN ('incident','maintenance','production')

### 2.3 SOP Token Explosion

**Observed issue:**

SOP chunks exceeding defined hard token limits

**Detection rule:**

- knowledge_type_effective = 'sop'
- chunk_token_count > SOP hard max

---

## Quarantine Contract

Corrupted rows are not dropped.
They are persisted.

A new Delta table was created:

**gold_knowledge_chunks_quarantine_v1**

### Columns:

- all original chunk columns
- corruption_reason STRING
- detected_at TIMESTAMP
- source_table_version STRING
- pipeline_run_id STRING

### Corruption reasons include:

- MALFORMED_EVENT_DATE_IN_TEXT
- MISSING_EVENT_DATE
- SOP_TOKEN_OVERFLOW
- UNKNOWN_CORRUPTION

Only corrupted rows are written to quarantine.
Embedding stage excludes them.

---

## Embedding-Ready Dataset (Semantic v2)

After removing quarantined rows, a clean dataset is created:

**gold_knowledge_chunks_semantic_v2**

### This table:

- Contains only APPROVED and non-corrupted chunks
- Preserves knowledge_chunk_id stability
- Does not mutate chunk_text
- Does not alter token counts
- Maintains full lineage

This table becomes the only source for embeddings.

---

## Embedding Table Contract

Embeddings are stored in a separate Delta table.

**gold_chunk_embeddings_v1**

### Schema:

- knowledge_chunk_id STRING
- embedding_model STRING
- embedding_vector ARRAY<FLOAT>
- embedding_dimension INT
- embedding_status STRING
- embedding_created_at TIMESTAMP
- pipeline_run_id STRING
- source_chunk_version STRING

This table never modifies chunk table.
Embeddings are always derived.

---

## Model Selection and API Pattern

Embedding calls use:

Databricks Secrets + REST API call pattern.

No mock model is used.
No inline hardcoded keys exist.

### Secrets stored:

- embedding_api_key
- embedding_api_base_url
- embedding_model_name

### Retrieved via:

dbutils.secrets.get(scope, key)

### REST call pattern:

- HTTPS POST
- JSON payload:
  ```
  {
    "input": chunk_text,
    "model": <model_name>
  }
  ```
- Bearer token authorization header
- Deterministic timeout
- Explicit error capture

Embedding dimension validated against expected model dimension.

---

## Idempotent Embedding Contract

Embeddings must never be duplicated.

### Rules:

- If knowledge_chunk_id already exists in embeddings table for given model, skip.
- If embedding_status = FAILED, eligible for retry.
- If embedding_status = SUCCESS, never re-embed.

### Join logic:

semantic_v2 LEFT ANTI JOIN embeddings_v1
ON knowledge_chunk_id AND embedding_model

Only new rows proceed to API.

---

## Batching Contract

Embedding API calls are executed in deterministic batches.

### Batch size default:

50 chunks per batch

### Hard cap:

100 per batch

Batch ID assigned using monotonically increasing batch index.

### Batch-level tracking:

- batch_id
- batch_size
- batch_start_time
- batch_end_time
- batch_status

No batch exceeds token safety envelope.

---

## Retry Policy Contract

### Retry rules:

- Retry up to 3 times per failed chunk
- Exponential backoff
- Retry only on:
  - 429 rate limit
  - 500 server errors
- Do not retry:
  - 400 validation errors
  - malformed input

### After max retries:

- embedding_status = FAILED
- row remains for next pipeline run

---

## Run Success Criteria

A pipeline run is considered SUCCESS only if:

- All eligible chunks were processed
- No batch-level failure remains
- embedding_vector dimension matches expected model dimension
- No NULL vectors stored
- Run metrics written

### If any condition fails:

- Run marked FAILED
- Alert triggered
- Embeddings not promoted

---

## Run Metrics and Alerting

### Metrics captured per run:

- total_chunks_scanned
- total_chunks_eligible
- total_chunks_quarantined
- total_chunks_embedded
- total_chunks_failed
- total_api_calls
- average_latency_ms
- p95_latency_ms
- total_tokens_processed
- cost_estimate

### Alerting rules:

- failure_rate > 2%
- vector_dimension_mismatch > 0
- quarantine_spike > threshold
- latency_p95 > SLA

### Metrics stored in:

embedding_run_metrics_v1

---

## Post-Embedding Validation

After write:

- embedding_vector IS NOT NULL
- embedding_dimension consistent across table
- row count matches number of successful embeddings
- sample cosine similarity test passes

Embeddings stage ends here.
Vector indexing begins only after these validations pass.