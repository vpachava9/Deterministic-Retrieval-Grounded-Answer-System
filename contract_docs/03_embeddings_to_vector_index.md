# Vector Indexing Pipeline Documentation

## Scope

This file documents the vector indexing stage from embeddings output to a FAISS index artifact and a retrieval-ready serving interface. This stage starts after embeddings are written and validated. This stage ends when FAISS index artifacts are published and basic retrieval smoke tests pass.

### Contract Status Markers

- **ENFORCED** means the rule is implemented in notebooks and the stage hard-fails when it is violated.
- **CHECKED** means the rule is checked in notebooks but may not hard-fail the stage.
- **SPECIFIED** means the rule is part of the indexing contract design but is not fully automated in the current notebooks.

---

## Inputs

- gold_knowledge_assets (Delta)
- gold_knowledge_chunks_embedding_ready_v3 (Delta)
- gold_knowledge_chunk_embeddings_v1 (Delta)

---

## Core Outputs

- vw_vector_index_input_v1 (view)
- vector exports for FAISS build (Parquet)
- FAISS index artifact (index.faiss)
- id_map artifact (Parquet)
- metadata snapshot for serving (Parquet)
- manifest.json (index metadata and lineage)

---

## Scope and Produced Artifacts

### Artifact Contract

- The index-input dataset is treated as the single authoritative source for indexing.
- The index artifact is treated as immutable once published.
- The index artifact directory is version-scoped and never overwritten in place.
- The index version encodes embedding model name, model version, embedding dimension, and build timestamp.

### Storage Zones

- **Export root path:** abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/vector_index/exports
- **Index root path:** abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/vector_index/faiss
- **Local build scratch path:** /dbfs/tmp/faiss_build/<index_version>
- **Local smoke test scratch path:** /dbfs/tmp/faiss_smoke
- **Local index cache path for serving:** /dbfs/tmp/index_cache

### Index Directory Naming

- index_name=<index_name> is a required directory segment.
- index_version=<index_version> is a required directory segment.
- index.faiss is the required binary index file name.
- id_map.parquet is the required mapping artifact file name.
- metadata.parquet is the required metadata snapshot file name.
- manifest.json is the required manifest file name.

### Manifest Fields

- index_name
- index_version
- embedding_model_name
- embedding_model_version
- embedding_dim
- similarity
- vector_count
- export_run_id
- built_at_utc
- index_file
- id_map
- metadata

---

## Post-Embeddings Readiness Gates

### Post-Embedding Validation Entry Condition

- Embeddings table contains only terminal rows for the intended pipeline run.
- Embeddings table contains SUCCESS rows for the model slice pinned for this index.
- Embeddings table contains no null embedding_vector for SUCCESS rows.
- Embeddings table contains consistent embedding_dimension for the pinned slice.
- Embeddings table contains vector length equal to embedding_dimension for the pinned slice.
- Embeddings table contains chunk_text_hash for each embedded row.
- Embeddings table contains embedded_at and pipeline_run_id for each embedded row.

### Post-Chunk Validation Entry Condition

- Chunk table contains is_quarantined flag.
- Chunk table contains eligible_at timestamp for embedding-ready rows.
- Chunk table contains stable knowledge_chunk_id.
- Chunk table contains chunk_text and chunk_token_count.
- Chunk table contains knowledge_type_effective.

### Cross-Table Integrity Gates

- **Join key contract:** embeddings.knowledge_chunk_id must match chunks.knowledge_chunk_id.
- **Join key contract:** chunks.knowledge_id must match knowledge.knowledge_id.
- Knowledge metadata is treated as authoritative for business_domain, event_date, equipment_id, line_id, source_reference.
- Chunk metadata is treated as authoritative for knowledge_type_effective, chunk_text, chunk_index, chunk_token_count.
- Embedding metadata is treated as authoritative for embedding_vector, embedding_dimension, embedding_model_name, embedding_model_version, embedded_at, pipeline_run_id.

### Index Model Pinning Gate

- EXPECTED_MODEL_NAME is pinned to text-embedding-3-large.
- EXPECTED_MODEL_VERSION is pinned to embed_ops_v1.
- EXPECTED_DIM is pinned to 3072.

### Index Similarity Contract

- Vectors are L2 normalized before indexing.
- FAISS IndexFlatIP is used as the index type.
- Cosine similarity is implemented as inner product on normalized vectors.

---

## Index-Input View Contract

### View Name Contract

- vw_vector_index_input_v1 is the canonical name for the index-input dataset.
- A temp view with suffix _temp may be created for downstream stages.

### View Assembly Sources

- chunks_filtered is sourced from gold_knowledge_chunks_embedding_ready_v3.
- knowledge_df is sourced from gold_knowledge_assets.
- embeddings_filtered is sourced from gold_knowledge_chunk_embeddings_v1.

### Chunk Eligibility Filters Applied Before Joins

- is_quarantined must equal false.
- eligible_at must be not null.

### Embedding Success and Pinning Filters Applied Before Joins

- status must equal SUCCESS.
- embedding_vector must be not null.
- embedding_dimension must equal EXPECTED_DIM.
- embedding_model_name must equal EXPECTED_MODEL_NAME.
- embedding_model_version must equal EXPECTED_MODEL_VERSION.

### Join Strategy Contract

- Embeddings join to chunks uses inner join on knowledge_chunk_id.
- Embedding-ready chunks that do not have a SUCCESS embedding are excluded.
- Chunks that do not exist for an embedding row are excluded.
- Joined embeddings plus chunks join to knowledge uses inner join on knowledge_id.
- Rows with missing knowledge metadata are excluded from index input.

### Collision Avoidance Contract

- Chunk columns are projected and aliased with c_ prefix before joins.
- Embedding columns are projected and aliased with e_ prefix before joins.
- Knowledge columns are projected and aliased with k_ prefix before joins.
- Final names are stable and match the index-input contract.

### Knowledge ID Mismatch Contract

- knowledge_id_mismatch is computed when embeddings.knowledge_id differs from chunks.knowledge_id.
- knowledge_id_mismatch must be false for all indexed rows.

### View Schema Contract

- chunk_id
- knowledge_id
- embedding_vector
- embedding_dim
- embedding_model_name
- embedding_model_version
- knowledge_type
- business_domain
- event_date
- equipment_id
- line_id
- source_reference
- chunk_index
- chunk_token_count
- chunk_text
- chunk_text_hash
- embedded_at
- embedding_run_id
- chunk_pipeline_run_id
- created_at
- knowledge_id_mismatch

### Index-Input Deduplication Contract

- A safety dropDuplicates is applied on (chunk_id, embedding_model_version) before view creation.
- Stage validation enforces uniqueness and fails if duplicates exist.

### Index-Input Validation Gate

- Stage 5B validation executes over the view.
- Stage 5B produces explicit counts for all validation rules.
- Stage 5B hard-fails by raising an exception if any hard rule fails.

### Hard Rules Enforced in Validation

- Total row count must be greater than 0.
- No nulls in required columns.
- No duplicate keys for (chunk_id, embedding_model_version).
- embedding_dim must equal expected dimension.
- size(embedding_vector) must equal embedding_dim.
- knowledge_id_mismatch must equal false.

---

## Vector Export and FAISS Build Contract

### Export Stage Contract

- Only validated index-input view rows are exported.
- Export uses deterministic ordering by chunk_id ascending.
- Vectors export contains a single column named vector.
- Metadata export contains an explicit snapshot of the metadata required for serving.
- Export is run-scoped by RUN_ID.

### Export Output Paths

- **vectors:** <export_root>/<run_id>/vectors
- **id_map:** <export_root>/<run_id>/id_map
- **metadata:** <export_root>/<run_id>/metadata

### Export Schema Contract for Vectors

- vector is an array of floats with length equal to embedding_dim.
- vector ordering aligns with metadata ordering.

### Export Schema Contract for Metadata

- chunk_id
- chunk_text
- knowledge_id
- knowledge_type
- event_date
- equipment_id
- line_id
- source_reference

### FAISS Build Stage Contract

- FAISS build reads vectors export into an in-memory numpy array X.
- FAISS build asserts X.ndim equals 2.
- FAISS build asserts X.shape[1] equals embedding_dim.
- FAISS build asserts vectors count equals metadata count.
- FAISS build normalizes X using faiss.normalize_L2.
- FAISS build uses faiss.IndexFlatIP(embedding_dim).
- FAISS build calls index.add(X).
- FAISS build asserts index.ntotal equals vectors count.

### Index Persistence Contract

- Index is written to a local DBFS path first.
- Index is copied from local DBFS path to the final ABFSS index file path.
- No partial index is published to the final folder.

### ID Mapping Contract

- FAISS internal ids are sequential integers from 0 to vector_count-1.
- id_map.parquet maps faiss_id to chunk_id.
- chunk_id in id_map is identical to the chunk_id in metadata.parquet.

### Metadata Snapshot Contract

- metadata.parquet is written to the index version folder.
- metadata.parquet is the retrieval-time source for chunk_text and filterable fields.

### Manifest Contract Enforcement

- manifest.json is written to the index version folder.
- manifest.json encodes index versioning and lineage.
- manifest.json is required for serving initialization.

---

## Execution Plan Contract

### Stage Boundaries

- Stage boundaries are frozen before execution.
- Stages are executed in a strict order.
- No downstream stage runs if the upstream stage hard-fails.
- Stage outputs are explicit and persisted when required.

### Stage List

1. Assemble index-input dataset in the compute runtime.
2. Validate index-input contracts in the compute runtime.
3. Export vectors and metadata for FAISS build in the compute runtime.
4. Build FAISS index artifact in Python.
5. Publish index artifacts to versioned ABFSS folder.
6. Run smoke tests for retrieval correctness.
7. Initialize serving runtime and run basic query contract tests.

### Promotion Contract

- Exports are written to a run-scoped directory.
- Index build reads only from the run-scoped export directory.
- Index build writes to a version-scoped directory under the FAISS root.
- Index version directories are immutable after publish.

### Security and Governance Contract

- Gold datasets are treated as read-only inputs.
- No writes back to Gold during indexing.
- Index artifacts are stored outside Delta tables as binary artifacts.
- Embeddings remain in Delta and are not duplicated inside index artifacts.

### Dataset Scaling Gate

- Index build is blocked if index-input row count is zero.
- Index build is blocked if exported vectors count is zero.
- Index build is blocked if vectors count and metadata count differ.

---

## Post-Embedding Integrity Contracts

- **Uniqueness key contract:** one embeddings row per (knowledge_chunk_id, embedding_model_version).
- **Terminal status contract:** SUCCESS rows have non-null embedding_vector.
- **Embedding dimension contract:** embedding_dimension is constant for the pinned model slice.
- **Vector payload contract:** vector length equals embedding_dimension.
- **Vector dtype contract:** vectors are cast to float32 for FAISS build.
- **SPECIFIED Vector norm contract:** no zero-norm vectors are allowed after normalization.
- **Text hash contract:** chunk_text_hash exists and is used for staleness detection.
- **SPECIFIED Staleness gate contract:** chunk_text_hash matches the current chunk_text_hash for the indexed chunk_id.

---

## Index Readiness Metadata Contract

- Each indexable row carries knowledge_type for filter scoping.
- Each indexable row carries event_date for time scoping.
- Each indexable row carries equipment_id for equipment scoping.
- Each indexable row carries business_domain for domain scoping.
- Each indexable row carries source_reference for grounding.

---

## Index-Input Join Integrity Checks

**SPECIFIED** These checks are part of the join integrity contract for this stage.

- **SPECIFIED Anti-join check:** embeddings SUCCESS rows without a matching chunk are counted and expected to be zero for the pinned slice.
- **SPECIFIED Anti-join check:** eligible chunks without a SUCCESS embedding for the pinned slice are excluded and counted.
- **SPECIFIED Anti-join check:** embeddings plus chunks without knowledge metadata are excluded and counted.
- **Mismatch check:** embeddings knowledge_id must equal chunks knowledge_id.

---

## Index-Input Schema Type Constraints

- chunk_id is a string.
- knowledge_id is a string.
- embedding_vector is an array of floats.
- embedding_dim is an integer.
- knowledge_type is a string.
- event_date is a date and may be null only if upstream contract allows it.
- embedded_at is a timestamp.

---

## Index-Input Exposure Contract

### Exposed to Vector Search

- chunk_id
- embedding_vector
- knowledge_type
- event_date
- equipment_id
- line_id
- business_domain
- source_reference
- chunk_text is included for direct grounding and debug.

### Not Exposed to Vector Search

- raw Gold columns are not carried into index artifacts.
- full metadata maps are not included in the index artifact.
- embedding error payloads are not included in the index artifact.
- pipeline internal intermediate DataFrames are not stored in the index artifact.

---

## Indexing Strategy Contract

- **Index family used:** flat exact search for inner product.
- **Metric used:** inner product on normalized vectors to represent cosine similarity.
- **Index type used:** IndexFlatIP.
- **Vector normalization used:** faiss.normalize_L2 on both database and query vectors.

### Alternative Index Strategy Options Documented

- Databricks Vector Search as managed indexing option.
- cloud AI Search vector search as managed indexing option.
- FAISS artifact indexing as portable prototype option.

### Integrity Note for Reviewers

This stage produces a FAISS index artifact and is treated as a portable prototype index system. This stage does not claim managed multi-tenant serving, automatic incremental sync, or SLA-backed availability. Index updates are handled by building a new index_version rather than mutating an existing index in place.

---

## Export Integrity Checks

- Exported vectors count matches index-input view count.
- Exported metadata count matches index-input view count.
- Exported vectors and metadata are aligned by deterministic ordering.
- Exported vectors are readable as Parquet.
- Exported metadata is readable as Parquet.

---

## FAISS Build Execution Constraints

- Vectors are loaded into driver memory for numpy conversion.
- Vector build uses float32 arrays.
- Normalization is applied before add.
- Index build is single-model and single-dimension per index version.

---

## FAISS Artifact Contract Boundaries

- IndexFlatIP performs exact search over all vectors for inner product.
- IndexFlatIP does not store application-level ids by default.
- Application-level identity is preserved via an external id_map artifact.

---

## Publishing Contract

- Index artifacts are published only after index.ntotal equals vector_count.
- Manifest is published only after index artifact is published.
- id_map and metadata artifacts are published in the same index version folder.

---

## Manifest Validation Contract

- manifest.embedding_dim matches index dimension.
- manifest.vector_count matches index.ntotal.
- manifest.embedding_model_name and version match the embedded slice.
- manifest.index_file path exists.
- manifest.id_map path exists.
- manifest.metadata path exists.

---

## Smoke Test Contract

- Smoke test runs against the published index version.
- Smoke test loads index.faiss into local DBFS path for faiss.read_index().
- Smoke test loads vectors export and uses one vector as the query.
- Smoke test expects the top hit to resolve to the query chunk_id in self-retrieval test.
- Smoke test resolves FAISS ids to chunk_id using id_map parquet.
- Smoke test outputs the resolved chunk_ids and verdict.

### Smoke Test Contract for Text Grounding

- Smoke test selects one SUCCESS embedding row joined to chunk_text.
- Smoke test uses that embedding_vector as query.
- Smoke test resolves hits to chunk_text for manual inspection.

---

## Retrieval Query Contract and Serving Behavior

### Serving Initialization Contract

- Index artifacts are loaded by index_name and index_version.
- Serving validates the index directory exists before loading.
- Serving validates required files exist: index.faiss, id_map.parquet, metadata.parquet, manifest.json.
- Serving copies index.faiss to local cache before loading into FAISS.
- Serving loads manifest.json as a Python dict.
- Serving loads id_map.parquet and builds an in-memory mapping.
- Serving loads metadata.parquet as a compute runtime DataFrame and as an in-memory lookup keyed by chunk_id.
- Serving validates id_map completeness and fails if any FAISS id cannot be resolved.

### Query Input Schema Contract

- query_text is required and must be a string.
- top_k is optional and defaults to config.defaults.top_k.
- top_k must be an integer and must be between 1 and config.limits.max_top_k.
- filters is optional and defaults to empty dict.
- request_id is optional and is generated when missing.
- index_name is required.
- index_version is required.

### Query Quality Gate Contract

- query_text is trimmed and normalized.
- query_text must satisfy min_query_chars.
- query_text must satisfy min_query_tokens.
- query_text must satisfy alpha token ratio threshold.
- query_text must not contain long repeated characters.

### Query Embedding Contract

- **CHECKED** The notebook retrieval demo used a mock embedder function for query vectors, separate from the embedding pipeline, to avoid external API dependency.
- **SPECIFIED** Production query embedding must call the same embedding provider, model name, model version, and dimension used to build the index.
- Query embedding output must be a 1D vector.
- Query embedding dimension must match manifest.embedding_dim.
- Query embedding vector is L2 normalized before FAISS search.

### Query Search Contract

- FAISS search uses index.search(query_vector.reshape(1, -1), top_k).
- **ENFORCED** Distances returned by IndexFlatIP are treated as similarity scores in the search_candidates contract.
- **SPECIFIED** Retrieval code must not apply L2 distance to similarity conversions when the index uses inner product scoring.
- Indices returned by FAISS are treated as FAISS internal ids.

### Candidate Resolution Contract

- FAISS ids are mapped to chunk_id using id_map.
- Chunk metadata is resolved using chunk_id as the key.
- Resolved results include similarity score and rank.

### Filtering Contract

- Filters are applied after FAISS search using resolved metadata.
- Filters supported in the current notebooks include knowledge_type_effective, equipment_id, and event_date_start and event_date_end.
- Filters that reject all candidates return an empty result set.

### Threshold Contract

- min_similarity is enforced on resolved candidates.
- A strong similarity floor is defined.
- Minimum strong hits is defined.
- Maximum similarity gap is defined.

### Ordering and Limits Contract

- Results are ordered by similarity descending.
- Results are truncated to top_k after all filters and thresholds.

### No-Results Behavior Contract

- If query fails validation, the request is rejected before FAISS search.
- If FAISS returns no candidates, an empty result set is returned.
- If all candidates are filtered out, an empty result set is returned.
- If all candidates fail similarity threshold, an empty result set is returned.

---

## Observability and Recovery Contracts

### Run Identity Contract

- RUN_ID is recorded for export and is included in manifest.export_run_id.
- INDEX_VERSION is recorded for index artifact directory naming.
- Embedding model identity is recorded for index version naming and manifest.

### Logging and Metrics Contract

- Stage 5A logs view creation and row counts for major steps.
- Stage 5B logs null counts for required columns.
- Stage 5B logs duplicate key counts.
- Stage 5B logs dimension mismatch counts.
- Stage 5B logs vector length mismatch counts.
- Stage 5B logs knowledge_id_mismatch counts.
- Stage 5C logs export paths for vectors, id_map, and metadata.
- Stage 5D logs index version and index artifact paths.
- Stage 5E logs smoke test pass or fail verdict.
- Serving logs missing artifacts and fails fast if index directory is incomplete.

### Failure Classification Contract

- Transient failures are treated as retryable at the orchestration layer.
- Permanent failures hard-fail the stage and require upstream correction.
- Schema mismatch, dimension mismatch, duplicate keys, and hash mismatch are permanent failures.
- Storage timeouts and cluster hiccups are transient failures.

### Recovery Contract for Export

- Export is rerunnable for a RUN_ID when output is written in overwrite mode to the run-scoped folder.
- Export row counts are compared to the index-input view row count.

### Recovery Contract for Indexing

- Index build writes locally first, then publishes to ABFSS.
- Index build does not overwrite an existing index_version folder for a successful run.
- Index build can be re-run by creating a new index_version.

### Recovery Contract for Serving

- Serving can reload index artifacts from ABFSS by index_name and index_version.
- Serving caches index.faiss locally to reduce repeated remote reads.
- Serving fails fast if the local cache cannot be created or written.

---

## Failure Modes and Recovery Contracts

### Assemble Stage Failures

**Failure:**
- missing source tables
- missing Delta log
- schema drift

**Recovery:**
- retry once for transient storage errors
- permanent fail for schema drift

### Validation Stage Failures

**Failure:**
- required column nulls
- duplicate keys
- dimension mismatch
- vector length mismatch
- knowledge_id_mismatch

**Recovery:**
- permanent fail and fix upstream

### Export Stage Failures

**Failure:**
- partial export write
- row count mismatch between export and index-input view
- export unreadable

**Recovery:**
- overwrite run-scoped export and rerun export

### Index Build Stage Failures

**Failure:**
- numpy conversion fails
- vector shape mismatch
- normalization fails due to zero norm vectors
- index.ntotal mismatch after add
- publish copy to ABFSS fails

**Recovery:**
- rerun build with a new index_version after resolving the root cause

### Smoke Test Failures

**Failure:**
- cannot load index artifact
- id_map missing or unreadable
- self-retrieval does not return self in top_k

**Recovery:**
- block publish and re-check deterministic ordering and id mapping

### Serving Failures

**Failure:**
- required files missing in index directory
- index manifest mismatch
- query embedding dimension mismatch

**Recovery:**
- fail fast and force operator to load correct index version

---

## Operational Guardrails

- No silent overwrites of index artifacts.
- No mixing embeddings models inside one index.
- No indexing of unvalidated rows.
- No serving of an index without a manifest.

---

## Primary External References for the FAISS Contract

- FAISS index type summary and the note that IndexFlatIP can be used for cosine similarity by normalizing vectors.
- FAISS metric guidance on mapping cosine similarity to inner product by normalizing both database and query vectors.
- FAISS research reference describing large-scale similarity search systems and motivating design patterns used in FAISS.