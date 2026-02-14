# Post-Vector Index Validation

Before retrieval is allowed to execute, the FAISS index and artifacts must pass integrity checks.

## 1.1 Artifact Existence Contract

For a given index_name and index_version, the following must exist:

- index.faiss
- id_map.parquet
- manifest.json

If any artifact is missing, retrieval fails with INDEX_NOT_FOUND.

## 1.2 Manifest Integrity Contract

manifest.json must contain:

- index_name
- index_version
- embedding_model_version
- embedding_dimension
- similarity_metric
- normalization_rule
- total_vectors
- build_timestamp

The manifest is treated as immutable.
If FAISS index dimension does not match manifest.embedding_dimension, retrieval fails.

## 1.3 ID Map Contract

id_map must contain:

- faiss_id (integer)
- chunk_id (string UUID)

### Rules:

- No NULL values
- faiss_id unique
- chunk_id unique
- Row count equals manifest.total_vectors

If mismatch detected, retrieval fails with MANIFEST_MISMATCH.

## 1.4 Similarity Metric Contract

Similarity metric is fixed:

Cosine similarity implemented as inner product on L2-normalized vectors using FAISS IndexFlatIP.

Range of scores: [-1, 1]

This must match manifest.similarity_metric.

---

## Retrieval System Boundary

### Retrieval is responsible for:

- Validating input request
- Loading pinned index artifacts
- Embedding the query
- Searching FAISS
- Resolving ids to chunks
- Applying strict filters
- Enforcing similarity thresholds
- Returning structured evidence
- Writing audit logs

### Retrieval is not responsible for:

- Prompt construction
- LLM execution
- Citation formatting
- Response synthesis

---

## Retrieval Request Contract

### 3.1 Required Fields

- query_text (string)
- index_name (string)
- index_version (string)

### 3.2 Optional Fields

- top_k (int, default from config)
- filters (object)
- min_similarity_override (float)
- request_id (string)

### 3.3 Validation Rules

**query_text:**

- Trimmed length > 0
- Max length enforced
- Reject control characters

**index_name:**

- Must exist in registry
- Case normalized

**index_version:**

- Must match published artifact directory
- Aliases such as "latest" rejected

**top_k:**

- Min 1
- Max from config
- Must be integer

**filters:**

Allowed fields only:

- knowledge_type_effective
- equipment_id
- event_date_start
- event_date_end

Date filters must satisfy start <= end.

### 3.4 Derived Internal Fields

- embedding_model_version
- embedding_dimension
- similarity_metric
- candidate_multiplier
- min_similarity_hard
- min_similarity_soft

These are loaded from manifest and config.
They cannot be overridden by request except threshold override within safe bounds.

---

## Query Embedding Contract

The query must be embedded using the same model version used during indexing.

### Rules:

- Embedding model version loaded from manifest
- Vector dimension must equal manifest.embedding_dimension
- Vector must be L2 normalized
- If dimension mismatch, retrieval fails

Embedding must use Databricks Secrets + REST API call pattern.
No hardcoded credentials allowed.

If embedding fails, status = FAILED.

---

## Candidate Search Contract

### 5.1 Candidate_k Calculation

candidate_k = top_k * candidate_multiplier

candidate_multiplier is configurable.

**Purpose:** over-fetch before filtering.

### 5.2 FAISS Search Rules

- Use IndexFlatIP
- Query vector must be normalized
- Return candidate_k nearest neighbors

If FAISS returns empty results and index is non-empty, status = NO_EVIDENCE.

### 5.3 Raw Candidate Output

Each candidate contains:

- faiss_id
- similarity score

No filtering applied at this stage.

---

## Resolve and Join Contract

### 6.1 ID Resolution

faiss_id mapped to chunk_id using id_map.

If any faiss_id cannot be resolved, retrieval fails.

### 6.2 Chunk Join

chunk_id joined with chunk metadata table:

- chunk_text
- knowledge_id
- knowledge_type_effective
- event_date
- equipment_id
- source_reference

Join must be lossless.
If join reduces row count, retrieval fails.

### 6.3 Order Preservation

Original FAISS rank order must be preserved.
No Spark join may reorder without explicit rank preservation.

---

## Filter Contract

Filters are strict constraints.

If a chunk does not satisfy filter conditions, it is removed.

No soft ranking boost logic is used.

### Supported filters:

- knowledge_type_effective
- equipment_id
- event_date range

SOP records with NULL event_date are excluded when date filters are applied.

Filtering occurs after candidate retrieval and join.

---

## Similarity Threshold Contract

Two thresholds are enforced:

- min_similarity_hard
- min_similarity_soft

### Rules:

- If no candidate survives filtering → NO_EVIDENCE
- If top similarity < min_similarity_hard → NO_EVIDENCE
- If top similarity >= hard threshold → SUCCESS

Soft threshold is used for confidence classification but does not change status.

Thresholds may vary by knowledge_type.

---

## Deterministic Ordering Contract

Final result ordering:

- **Primary:** similarity DESC
- **Secondary:** chunk_id ASC

Results must be stable across identical runs.

---

## Response Schema Contract

### Top-level fields:

- request_id
- status
- index_name
- index_version
- embedding_model_version
- similarity_metric
- filters_applied
- top_k_requested
- results_returned

### Status values:

- SUCCESS
- NO_EVIDENCE
- FAILED

### Results array (if SUCCESS):

- rank
- chunk_id
- similarity
- knowledge_id
- knowledge_type_effective
- event_date
- equipment_id
- chunk_text
- source_reference

No hidden reordering allowed.

---

## Failure Semantics

### FAILED:

- Validation error
- Artifact load error
- Dimension mismatch
- Embedding failure
- Join failure

### NO_EVIDENCE:

- All candidates filtered
- Top similarity below threshold
- Index empty

### SUCCESS:

- At least one result survives
- Top similarity >= hard threshold

Retrieval never fabricates fallback results.

---

## Logging and Audit Contract

### 12.1 retrieval_requests_v1

One row per request.

**Columns:**

- request_id
- requested_at
- index_name
- index_version
- embedding_model_version
- query_text_hash
- top_k_requested
- candidate_k
- filters_json
- min_similarity_hard
- status
- results_returned
- top_similarity
- embed_ms
- faiss_ms
- resolve_ms
- join_ms
- total_ms
- error_code

### 12.2 retrieval_results_v1

One row per returned chunk.

**Columns:**

- request_id
- rank
- chunk_id
- similarity
- knowledge_id
- knowledge_type_effective
- event_date
- equipment_id
- index_version

Logs are append-only.
No mutation allowed.

---

## Debug and Observability

Debug counters include:

- candidate_k
- rejected_by_filter_count
- rejected_by_threshold_count

Timing metrics per stage.

Raw query text is never stored.
Only hashed version retained.

---

## Reproducibility Guarantees

Given identical:

- query_text
- index_version
- filters
- top_k

System guarantees identical results and ordering.

### This is achieved by:

- Pinned index_version
- Stable ordering rules
- Immutable artifacts
- Deterministic filtering

---

## Governance and Retention

- **retrieval_requests retention:** 90 days
- **retrieval_results retention:** 90 days
- Aggregated metrics retained longer

No raw query text retention beyond necessary window.

---

## Core Design Principles

- Determinism over heuristics
- Fail fast over silent corruption
- Strict filters over soft ranking
- Explicit thresholds over blind trust
- Immutable artifacts over mutable state

Retrieval is treated as a safety-critical subsystem.

---

## What Retrieval Guarantees

- Never returns fabricated evidence
- Never ignores filter constraints
- Never uses wrong embedding model
- Never mixes index versions
- Never hides failure
- Always logs outcomes

Retrieval ends here.
Answer assembly begins after this stage.