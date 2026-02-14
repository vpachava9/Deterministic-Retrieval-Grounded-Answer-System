# Project README: End-to-End RAG Pipeline

## Executive Summary

I built a multi-stage retrieval-augmented generation (RAG) pipeline that processes raw data through six distinct stages: 
- **Gold → Knowledge → Chunking**  
- **Chunking → Embeddings**  
- **Embeddings → Vector Index (FAISS)**  
- **Vector Index → Retrieval**  
- **Retrieval → Answer Assembly**  
- **Answer Assembly → Post-generation Validation & Response**  

Each stage produces clearly defined datasets, enforces strict contracts, and generates audit artifacts. The pipeline is orchestrated so that no stage modifies upstream raw data; each output is the sole input to the next. We recorded detailed validation results at each step and packaged final answers in a stable public schema. 

In total, the project delivered: unified knowledge and chunk tables, an embeddings dataset, a FAISS index with ID mapping, a vector search-enabled retrieval table, an assembled prompt and model output, a grounded answer with citations, and audit logs of validation checks. All code uses **Databricks Secrets + REST API** for embedding calls and respects production-grade best practices. 

The sections below summarize **what I did** at each stage, including key artifacts, schemas, contracts, and validations.  The final section wraps up the core outcomes and architecture guarantees.

    Gold→Knowledge→Chunks    
    Chunks→Embeddings            
    Embeddings→VectorIndex     
    VectorIndex→Retrieval     
    Retrieval→AnswerAssembly     
    AnswerAssembly→Validation    




## Stage 1: Gold → Knowledge → Chunking

**Inputs:** Separate raw CSVs in Gold storage (incidents, quality, maintenance, production, SOP).

**Outputs:**  
- `knowledge/gold_knowledge_assets` (Delta table)  
- `knowledge/gold_knowledge_chunks` (Delta table)  

Loaded all gold CSVs as read-only and created a unified **Knowledge** table with a fixed schema. For each dataset (Incidents, Quality, Maintenance, Production, SOP), we did the following:

- **Schema Enforcement:** Created an empty Delta table with explicit fields: `knowledge_id`, `knowledge_type`, `business_domain`, `content_text`, `source_reference`, `event_date`, and a `metadata` map.  
- **Transformation:** For each dataset, we populated these fields:
  - **knowledge_id:** Generated UUIDs or used existing IDs (e.g. metric_id, maintenance_id).  
  - **knowledge_type:** Hard-coded per source (e.g. `'incident'`, `'quality'`, `'maintenance'`, `'production'`, `'sop'`).  
  - **business_domain:** Set per source (e.g. `'operations'`, `'quality'`, `'manufacturing_operations'`).  
  - **content_text:** Concatenated descriptive fields (dates, actions, outcomes) into a narrative text for each row.  
  - **source_reference:** Included stable identifiers (e.g. original IDs or CSV filenames).  
  - **event_date:** Derived from a date field in the source.  
  - **metadata:** Captured all other relevant fields as a key-value map.  

After writing all knowledge records, I ran validation checks to confirm: all required columns existed, key fields were non-null (`knowledge_id`, `content_text`, etc.), and no rows were silently dropped. I reviewed row counts and domain distributions to ensure completeness.

Next, I created the **Chunk** table with a strict schema:

- **Fields:** `knowledge_chunk_id` (UUID), `knowledge_id`, `knowledge_type_original`, `knowledge_type_effective`, `chunk_index`, `chunk_text`, `chunk_token_count`, plus lineage fields.
- **Eligibility Filters:** Marked rows APPROVED or REJECTED before chunking. We rejected any row with null or placeholder content (like `"n/a", "none", "OK"`), and rows too short (less than ~120 chars without action or numeric signal). These filters are *pre-chunking checks*.
- **Chunk Generation:** For each approved Knowledge row:
  - For types **incident** and **production**, we created *one chunk per row* (index 0) and carried over text.
  - For **maintenance** and **quality**, we also made each row a single chunk.
  - For **SOP**, we split the content into multiple chunks using regex on section headings and a custom UDF to limit chunk size. Each SOP chunk was assigned an increasing `chunk_index`.
- **Token Estimate:** We computed `chunk_token_count` as `length(chunk_text)/4` (a heuristic).
- **Write Behavior:** We appended chunks into `knowledge/gold_knowledge_chunks`.  

validated the chunk table by checking that all `knowledge_chunk_id` values were unique and non-null, all `chunk_text` was non-null and of reasonable length, and token counts were positive. 

**Stage 1 Summary:** Knowledge Assets and Chunk tables now exist with unified schema and clean narrative text. This completes data normalization from Gold CSVs into the first RAG staging tables.

---

## Stage 2: Chunking → Embeddings

**Inputs:**  
- `knowledge/gold_knowledge_chunks` (from Stage 1).  

**Outputs:**  
- `knowledge/gold_knowledge_chunks_semantic_v2` (Delta table of approved chunks)  
- `knowledge/gold_knowledge_chunks_quarantine_v1` (Delta table of quarantined chunks)  
- `embeddings/gold_chunk_embeddings_v1` (Delta table of embedding vectors)  
- `metrics/embedding_run_metrics_v1` (Delta table of run metrics)  

In this stage I prepared chunks for embedding and called the embedding API.

**Preconditions:** Before calling embeddings, we enforced:
- **Stability Checks:** Confirmed every `knowledge_chunk_id` and `knowledge_id` was non-null and unique. No duplicates.  
- **Content Checks:** Ensured `chunk_text` was not blank or placeholder. Verified `chunk_token_count > 0` and within expected ranges.  
- **Schema Checks:** Loaded the chunk table to confirm schema columns matched exactly what Stage 1 defined.

**Corruption Detection:**  identified and quarantined malformed chunks rather than dropping them:
- Detected chunks with malformed dates in text (e.g. “On 125 ,”) or missing required `event_date` for certain types (incident, production, maintenance).
- Identified any SOP chunks exceeding a hard token limit.
- All such corrupted rows were written to `gold_knowledge_chunks_quarantine_v1` with additional columns: `corruption_reason`, `detected_at`, and pipeline metadata.

**Semantic (Embedding-Ready) Table:**  created `gold_knowledge_chunks_semantic_v2` containing only the **approved** chunks (filtering out quarantined ones). We did **not** alter `chunk_text` or tokens. This table was persisted and used as the sole source for embeddings.

**Embedding-Ready Dataset Contract:** It preserves lineage (`knowledge_chunk_id`), includes all original fields, and is append-only (never reordering or dropping content beyond quarantine).

**Embedding Model/API:** used a real embedding model via REST:
- **Configuration:** Model name and API key are stored in Databricks Secrets. 
- **API Calls:** For each chunk, we called the embedding endpoint with JSON payload `{"input": chunk_text, "model": "<model_name>"}`.
- **Idempotency:** Before calling, we anti-joined against existing embeddings in `gold_chunk_embeddings_v1`. If a `knowledge_chunk_id` already had a successful embedding for the model, we skipped it. Failed embeddings could be retried. 
- **Batching:**  sent chunks in deterministic batches (default 50, cap 100). Batches were logged with a batch ID and timestamps.
- **Retries:** Failed calls (due to 429 or server errors) were retried up to 3 times with backoff. Permanent failures (400-range) were marked as failures and retried in the next run.
- **Output:** Successful embeddings (float arrays) were stored in `gold_chunk_embeddings_v1` with fields: `knowledge_chunk_id`, `embedding_model`, `embedding_vector`, `embedding_dimension`, `embedding_status` (SUCCESS/FAILED), `embedding_created_at`, `pipeline_run_id`, `source_chunk_version`.

**Run Metrics:**  collected run-level metrics in `metrics/embedding_run_metrics_v1`: total chunks scanned, chunk_count_embedded, chunk_count_failed, API call count, latency, etc. Alerts were specified (e.g. failure rate, dimension mismatches) but not detailed here.

**Stage 2 Summary:**  produced a clean embedding-ready chunk table and the resulting embeddings table, with corrupted chunks quarantined. All API calls used the Databricks secret-backed REST pattern. The system logged batch and run metrics.

---

## Stage 3: Embeddings → Vector Indexing

**Inputs:**  
- `knowledge/gold_knowledge_chunks_semantic_v2` (approved chunks)  
- `embeddings/gold_chunk_embeddings_v1` (completed embeddings)  

**Outputs:**  
- **Index-Input View:** A merged view of chunks + embeddings + metadata.  
- `vector_index/index_table` (Delta view or temp view for indexing).  
- `vector_index/faiss_index.index` (FAISS binary index artifact).  
- `vector_index/id_map.parquet` (parquet mapping FAISS IDs to chunk IDs).  
- `vector_index/metadata.parquet` (parquet of chunk metadata for search).  
- `vector_index/manifest.json` (index metadata with embedding model, dimension, vector count, etc.).  

In this stage, I assembled data for FAISS indexing and built the index.

**Index-Input View:**  performed joins (in Spark) to combine:
- All **SUCCESS** embeddings for the pinned model version.
- The corresponding chunk rows.
- Knowledge metadata (filter columns like `event_date`, `equipment_id`).

I enforced:
- **Join Integrity:** Inner join on chunk IDs; we checked no orphan embeddings or chunks.
- **Schema Contract:** The view has fixed columns: `chunk_id`, `knowledge_id`, `embedding_vector`, `embedding_dim`, `knowledge_type`, `event_date`, `equipment_id`, `line_id`, `business_domain`, `source_reference`, `chunk_text` (for debugging).
- **Dimension Consistency:** Asserted `embedding_dim` matches expected (e.g. 1536 for text-embedding-3-large).
- **Null Checks:** Validated no null vectors or keys.

**FAISS Build:**  loaded the `embedding_vector` column into a NumPy array (float32) and normalized it (L2 normalization for cosine). We created a FAISS IndexFlatIP with the pinned dimension and added all vectors. After building:
-  verified `index.ntotal == number_of_vectors`.
-  wrote the index to a local file and then uploaded to `vector_index/index_name=<NAME>/index_version=<VER>/index.faiss`.
-  generated an `id_map.parquet` mapping sequential FAISS IDs to `chunk_id`.
-  wrote `metadata.parquet` with chunk metadata from the index-input view (same ordering as vectors).
-  created `manifest.json` recording: index path, model name/version, embedding_dim, vector_count, etc., and saved it alongside the index.

**Smoke Test:** After publishing, I loaded the FAISS index and id_map, ran a self-query using one of the vectors, and confirmed the retrieved top ID matched the original chunk. This tested end-to-end correctness.

**Stage 3 Summary:** All chunk embeddings were loaded into a FAISS exact-search index.  produced the index artifact and mapping files under a versioned path. No external index services were used. The index is now ready for query.

---

## Stage 4: Vector Index → Retrieval

**Inputs:**  
- FAISS index (the `index.faiss` file)  
- `vector_index/metadata.parquet` (chunk metadata)  
- A user query with optional filters (`knowledge_type`, `equipment_id`, date range).  

**Outputs:**  
- `retrieval/candidate_rows` (in-memory or temp table of filtered search results)  
- A **document search function** (not persisted here)  
- Logs of query processing  

In this stage I handled user queries and returned relevant chunk candidates.

**Query Schema:** Each retrieval request includes:
- `request_id` (unique)
- `query_text`
- `top_k`
- Optional `filters`: lists of `knowledge_type_effective`, `equipment_id`, and `event_date` range.
- Required `index_name` and `index_version`.

**Request Validation:**  enforced a validation schema:
- `top_k` must be between 1 and config max.
- Filters (if present) must be proper lists or dates.
- The index specified must exist (manifest present).

**Query Embedding:**  embedded the `query_text` using the same embedding model (via Databricks Secrets + REST) to produce a `query_vector`.

**Vector Search:**  loaded the FAISS index into memory, normalized `query_vector`, and called `index.search(query_vector, candidate_k)`.  treated FAISS similarities as cosine scores. We then mapped FAISS IDs back to `chunk_id` using `id_map`.

**Filtering & Thresholding:** After search:
- **Filter Conditions:** Applied `knowledge_type`, `equipment_id`, and date filters on the joined results using the metadata. If a chunk fails a filter, it was excluded.
- **Similarity Thresholds:**  enforced a minimum similarity (e.g. 0.76, as per policy) and a strong/hot hit rule.
- **Candidate Limits:**  trimmed results to `top_k` by score.

**No-Results Handling:** If no chunks remained after filters and thresholds,  return an empty result set (signaling the downstream layer to handle NO_EVIDENCE).

**Retrieval Result:** The result is a ranked list of chunks (with `knowledge_id`, `chunk_id`, `similarity`, metadata fields). This is used immediately in Answer Assembly.

**Stage 4 Summary:** e executed fast approximate nearest-neighbor search on the FAISS index for each user query, then applied exact filters and similarity cuts. This yielded a final sorted list of candidate chunks per query.

---

## Stage 5: Retrieval → Answer Assembly

**Inputs:**  
- Ranked candidate chunks from retrieval (with `chunk_text` and metadata).  
- Original user question and filters.  
- Policy configuration (thresholds, max chunks, token budgets).  

**Outputs:**  
- An **AnswerBundle** object (in code) containing selected chunks, assembled answer text, and reference anchors.  
- A constructed LLM prompt string.  
- The raw LLM response text.  

In this stage, I built the final input for the LLM and ran it.

**Chunk Selection:**  applied the assembled policy to the retrieval results:
- **Similarity Gate:**  required each chunk’s similarity ≥ *policy threshold* (unspecified here; original policy said ~0.76). Chunks below this threshold were not used.
- **Chunk Limits:**  limited total number of chunks (e.g. max 5) and checked per-source limits. 
- **Token Budget:**  accumulated `chunk_token_count` and pruned lowest-ranked chunks if  exceeded the evidence token budget.
- **Ordering:** Maintained original retrieval order for anchors.
  
Selected chunks were labeled sequentially as citations C0, C1, etc.

**AnswerBundle Assembly:**  combined the selected chunks into an `AnswerBundle`:
- Fields: `query_text`, `selected_chunks` (with `chunk_text` and metadata), `citations` (the anchors), and `context` fields (e.g. pipeline versions).
- The bundle did not contain full chunk contents for final user output, only references.

**Prompt Construction:**  filled a prompt template with:
- A system message (instruction to answer using evidence).
- The question text.
- The selected chunk excerpts (each labeled by its anchor).
- A final instruction to answer truthfully and cite sources.
  
The resulting prompt string was **frozen in code** (no dynamic templates, all sections fixed by contract).

**LLM Execution:** We sent the prompt to the language model (e.g. GPT-4o) with:
- Preset parameters (temperature=0.0 for deterministic output).
- An output token limit.
- Recorded `prompt_tokens` and `completion_tokens`.
- We captured the raw LLM answer text and latency.

No content filtering was applied at this point.

**Stage 5 Summary:** I enforced our chunking and prompt policies, built a stable prompt, and obtained an answer from the LLM. The answer and chunk anchor references were stored in an internal bundle for validation.

---

## Stage 6: Post-Generation Validation & Response

**Inputs:**  
- The raw LLM answer text (with citation anchors).  
- The AnswerBundle (list of anchors and sources).  

**Outputs:**  
- An internal **ValidationResult** object (pass/fail, reasons, metrics).  
- A record appended to `logs/r5_validation_results` (Delta table).  
- A final **PublicResponse** JSON (or object) returned to user.  

In this final stage, I strictly checked that the answer adhered to evidence:

**Validation Checks:**  ran all post-generation rules:
- **Citation Format:** Extracted anchors (C0, C1, …). Verified each anchor exists in the AnswerBundle’s citations. If an anchor was invalid or missing, mark `INVALID_CITATION_REFERENCE`.
- **Factual Coverage:** Split the answer into sentences and ensured each factual sentence contained at least one valid citation. If any factual claim lacked citation, mark `UNCITED_FACTUAL_STATEMENT`.
- **Refusal Handling:** If the answer is a “no evidence” response, checked that it exactly matches the refusal template. Any deviation is `INVALID_REFUSAL_FORMAT`.
- **Answer Sanity:** If any of the above fails, the validation status is FAILED. Otherwise PASSED.
- **Metrics:** Counted citations, uncited sentences, invalid anchors, etc. We logged flags like `refusal_detected` or suspicious length ratio.

**Validation Persistence:** We appended a row to `logs/r5_validation_results` with fields:
  ```
  {
    request_id,
    run_id,
    timestamp_utc,
    generation_status,    // OK, NO_EVIDENCE, or FAILED
    validation_status,    // PASSED or FAILED
    failure_reason (if any),
    citation_count,
    uncited_sentence_count,
    invalid_anchor_count,
    refusal_detected,
    length_ratio_flag,
    validated_citations,
    validated_answer_text, // if PASSED
    model_name,
    embedding_model,
    index_version,
    policy_version
  }
  ```
This record provides an audit trail of each request’s outcome.

**Public Response Packaging:** Finally, converted our internal result into the public API schema:
- For **PASSED** answers: `status="OK"`, include `validated_answer_text`, and a list of public citations. Each citation object includes `{anchor, knowledge_id, source_reference, event_date, equipment_id}`.
- For **NO_EVIDENCE** (refusal): `status="NO_EVIDENCE"`, include the refusal text as `answer`, and no citations.
- For **FAILED** validation: `status="FAILED"`, with empty answer and citations.
- In all cases, I included `request_id`, token usage (prompt/completion/total), and `latency_ms`.

The PublicResponse schema is fixed. I did **not** expose any internal debug fields (no raw chunk_text or debug IDs).

**Stage 6 Summary:**  enforced final grounding checks, logged validation outcomes to Delta, and produced a clean public response JSON. The pipeline run for that request is now fully complete.

---

## Final Wrap-Up (Conclusion)

This pipeline implements a fully production-ready RAG system. Each stage produces durable artifacts and enforces immutability of upstream data. Data flows one-way: raw Gold → Knowledge → Chunks → Embeddings → Index → Retrieval → Answer → Response. There are strict contracts and validation gates at every handoff.

 processed multiple raw domains (incidents, quality, maintenance, production, SOP) into unified knowledge and chunk formats. I caught and quarantined any malformed data before embeddings. Used Databricks Secrets + REST calls for embeddings and queries. We built a FAISS exact-index for similarity search and loaded it for fast queries. I applied deterministic chunk selection and thorough prompt construction. Validated the final answer against citations and logged results in Delta.

**Key outcomes:**

- **Reproducibility:** All thresholds, schemas, and orderings are fixed. Re-running with the same data and policy yields identical results.
- **Grounding Safety:** The validator ensures no hallucinated content. Answers with missing or bad citations are rejected.
- **Auditability:** Every request’s generation and validation metrics are stored for review.
- **Separation of Concerns:** Internal tables and logs are kept separate from the public API output.
- **Configuration:** All policy thresholds and versions are recorded in a manifest, ensuring transparency of model, index, and policy choices.


