# Answer Assembly to Public Response

## Scope

This stage starts after retrieval has produced a ranked list of evidence candidates and ends with a stable public response object plus persisted validation records.

### Layers Covered in This Document:

- **R2:** Chunk selection and answer assembly
- **R3:** Prompt builder
- **R4:** LLM execution
- **R5:** Post generation validation
- **R5 persistence:** Store validation results
- **R6:** Response packaging to a public schema



---

## Inputs

Inputs required at the entry of this stage:

- retrieval_bundle (request metadata + ranked retrieval rows)
- policy object (frozen policy version)
- run metadata (run_id, index_version, embedding_model)
- trace fields from earlier stages that must be propagated

---

## Outputs

Outputs produced at the end of this stage:

- answer_bundle (internal structured bundle for prompt and citations)
- llm_result (raw model output plus execution metadata)
- r5_validation_result (pass fail result plus grounding metrics)
- delta record of validation results written to storage
- PublicResponse object (API safe response payload)

---

## Contracts Frozen for This Stage

This stage is contract first. The contracts were frozen before implementation and enforced as fail fast validations.

### Frozen Contract Groups:

- Answer assembly contract
- Retrieval bundle input contract for R2
- Chunk selection rules and policy contract
- Prompt contract
- Token allocation contract
- LLM execution contract
- Post generation validation contract
- Response packaging contract

---

## R2 Input Contract

R2 receives one deterministic wrapper payload so later stages can reproduce decisions.

### R2 Input Schema Includes:

- **request_id** (required)
- **user_question** (required)
- **retrieval_status** (required enum: SUCCESS, NO_EVIDENCE, FAILED)
- **index_version** (required)
- **embedding_model** (required)
- **top_k** (required)
- **results** (required list of retrieval_result_row)
- **run_id** (optional but recommended)
- **retrieval_latency_ms** (optional)
- **filters_applied** (optional object with equipment_id, knowledge_type, date range)

### Each retrieval_result_row Must Include:

**Required fields:**

- chunk_id (not null)
- rank (not null, must start at 0, strictly increasing)
- faiss_id (not null)
- similarity (not null, finite, 0.0 to 1.0)
- chunk_text (not null, must be non empty after sanitization)
- knowledge_type_effective (not null)

**Nullable allowed:**

- equipment_id (nullable but must respect filter semantics)
- event_date (nullable only if allowed by domain rules)

---

## R2 Fail Fast Validations

R2 fails fast before any assembly work.

### Validation Groups:

**V1 schema validation:**

- All required fields exist
- Types match expected schema
- Results list exists and is a list

**V2 rank integrity:**

- ranks are unique
- ranks strictly increasing starting at 0
- results are already ordered by rank or R2 will reorder deterministically

**V3 similarity integrity:**

- similarity is finite number
- 0.0 <= similarity <= 1.0
- if retrieval_status is SUCCESS then top similarity must exist

**V4 text integrity:**

- chunk_text not empty
- after sanitization not empty

**V5 domain integrity:**

- knowledge_type_effective must be within allowed set

### Equipment ID Null Semantics Decision

If request includes equipment_id filter, rows with equipment_id null are not allowed to pass silently.

Implemented behavior is to drop invalid rows under an equipment_id filter.

If all rows are dropped, the system returns NO_EVIDENCE.

This prevents incorrect matches from flowing into prompt.

---

## Chunk Selection Rules (R2 Policy)

Chunk selection is policy driven and deterministic.

The policy defines what evidence is allowed into the prompt.

### Selection Behavior Enforced:

- Start from retrieval rank order
- Apply similarity gating before evidence admission
- Cap number of chunks
- Cap per knowledge_id, do not force only one per knowledge_id
- Deduplicate near duplicates by overlap ratio
- Enforce per chunk token ratio cap
- Enforce total evidence token budget
- Keep deterministic ordering for stable citation anchors

**Important:** similarity gate value must be consistent.

our attached contracts freeze min_top_similarity_score at 0.76.


## Evidence Sanitization Rules

Evidence text is normalized without changing meaning.

### Sanitization Mode Used:

- remove control characters
- normalize whitespace
- strip null bytes
- do not rewrite semantics

Goal is to prevent broken text or hidden characters from corrupting prompt structure.

---

## Deterministic Ordering Contract

Evidence ordering must be deterministic.

### Ordering Mode Frozen:

ordering_mode = rank_strict

- **primary sort:** rank ascending
- **tie break:** chunk_id ascending

No dependency on Spark partition order or Python dict order.

This ordering controls citation anchors and reproducibility.

---

## NO_EVIDENCE Escalation Rule

Strict NO_EVIDENCE handling is enabled.

If after filtering, dedupe, and token pruning no valid evidence remains:

- assembly_status = NO_EVIDENCE
- downstream prompt generation is blocked from making factual claims
- the model must return the refusal format for NO_EVIDENCE

No silent continuation.

---

## Answer Assembly Output Contract

R2 produces an AnswerBundle that is consumed by prompt builder and validator.

### AnswerBundle Includes:

- request_id
- assembly_status (OK, NO_EVIDENCE, FAILED)
- used_chunks (selected evidence rows with metadata)
- citations (stable anchors C0, C1, C2, ...)
- trace metadata (index_version, embedding_model, policy_version, run_id)
- assembly metrics (selected_k, dropped counts, evidence token totals)

### Citation Anchor Contract:

- Anchors are stable and sequential: C0, C1, C2 ...
- Anchor assignment is consistent with evidence ordering
- Anchors map to exactly one selected chunk

---

## Prompt Contract (R3)

Prompt shape is frozen and versioned.

Prompt builder is not allowed to invent structure at runtime.

### Prompt Template Structure Used:

1. system instruction block first
2. safety and refusal rules included
3. evidence section with strict formatting and citation anchors
4. question section separate
5. output instruction block frozen

Prompt builder must produce the exact prompt bytes that will be sent to the model.

---

## Token Allocation Contract

Token budgets are enforced before calling the model.

### Allocation Fields:

- max_total_prompt_tokens
- max_evidence_tokens
- reserved_output_tokens
- max_chunk_token_ratio

### Enforced Behaviors:

- evidence must stay under max_evidence_tokens
- if exceeded, prune lowest rank first
- if still exceeded, apply deterministic trimming within a chunk
- never exceed max_total_prompt_tokens
- no single chunk can consume more than max_chunk_token_ratio of evidence budget
- overlap dedupe uses overlap_ratio_threshold

This prevents truncation, broken citations, latency spikes, and cost blowups.

---

## Prompt Integrity Contract

Execution layer must not mutate prompt.

Prompt bytes produced by prompt builder are the bytes sent to the model.

### Disallowed Behaviors:

- no trimming or reformatting in execution
- no hidden prefix or suffix added
- no reordering of sections
- no insertion of extra system instructions

Prompt hash is computed and logged for audit.

---

## LLM Execution Contract (R4)

LLM execution is a thin wrapper over the frozen prompt.

### Execution Constraints Enforced:

- fixed model identity, no silent fallback
- temperature frozen at 0.0 for determinism
- output token cap frozen
- retries only for transient failures (timeouts, 429, 5xx)
- retries reuse the exact same prompt bytes
- no parameter drift between retries
- execution logs latency and token usage
- records provider response id for audit

Implementation uses OpenAI Responses API pattern

This stage does not change embeddings logic. It only consumes earlier trace fields like embedding_model and index_version from AnswerBundle trace.

### LLM Execution Tests Run

All 5 tests passed for this layer, focusing on invariants:

- no prompt mutation
- no silent fallback
- no parameter drift
- no prompt corruption across retries
- no contract violation output shape

---

## LLM Execution Output Schema

LLM execution returns a structured result object including:

- generation_status (OK, FAILED, NO_EVIDENCE)
- raw_model_text
- model_name
- prompt_sha256
- response_id
- llm_latency_ms
- **token usage fields when available:**
  - prompt_tokens_actual
  - completion_tokens_actual
  - total_tokens_actual

No parsing or editing of model output occurs here.

---

## Post Generation Validation Contract (R5)

R5 is a strict validator. It is a firewall.

R5 does not call any model.

R5 verifies that the model obeyed grounding rules and citation requirements.

### R5 Output Schema is Frozen:

- request_id
- generation_status: OK | FAILED | NO_EVIDENCE
- validation_status: PASSED | FAILED
- failure_reason: optional string
- validated_answer_text
- validated_citations (list of anchors)
- **grounding_metrics object with:**
  - citation_count
  - uncited_sentence_count
  - invalid_anchor_count
  - refusal_detected
  - length_ratio_flag
  - suspicious_new_ids when applicable

### No Silent Modification Rule:

R5 does not rewrite the answer text.

It either accepts it as validated or rejects it.

---

## R5 Validation Rules Enforced

### Citation Extraction Contract

- Extract anchors using regex pattern like [C<number>]
- Anchors must match the exact format with uppercase C
- No malformed anchors like [c0], (C0), [C-1]

### Allowed Anchor Set Contract

- Allowed anchors are exactly the set of citation_anchor values from AnswerBundle
- Every cited anchor must exist in allowed set
- Any invented anchor fails validation with failure_reason INVALID_CITATION_REFERENCE
- invalid_anchor_count increments

### Sentence Grounding Contract

- Every factual sentence must contain at least one citation
- Sentence segmentation rule splits on ., ?, !
- Empty segments ignored
- If a sentence contains a factual claim and no citation, fail with UNCITED_FACTUAL_STATEMENT
- uncited_sentence_count increments

### Refusal Format Contract

- Refusal must match the exact refusal string for NO_EVIDENCE
- Bad refusal formatting fails with INVALID_REFUSAL_FORMAT
- refusal_detected flag is set when refusal pattern is present

### Closed World Contract

The answer must not introduce unsupported facts outside provided evidence.

R5 enforces this through citation and anchor validation gates.

If citations are missing, invented, or uncited sentences exist, answer is rejected.

### Citation Consistency Contract

- validated_citations must not contain duplicates
- validated_citations must not include unused anchors
- mismatch fails with CITATION_MISMATCH

### Output Length Sanity Contract

- If answer length is more than 10x evidence length, flag as suspicious
- This is a metric flag only, not an automatic failure
- length_ratio_flag is recorded

### Strict Behavior on Failure

If validation fails:

- generation_status = FAILED
- validated_answer_text = empty
- failure_reason populated




---

## R5 Validation Tests Executed

Tests required and executed for R5:

**Test 1 valid answer passes:**

- expected validation_status PASSED
- expected generation_status OK
- validated_citations contains only allowed anchors

**Test 2 invented citation fails:**

- add [C99] to answer text
- expected FAILED
- failure_reason INVALID_CITATION_REFERENCE

**Test 3 uncited factual sentence fails:**

- add factual sentence without citation
- expected FAILED
- failure_reason UNCITED_FACTUAL_STATEMENT

**Test 4 bad refusal fails:**

- set raw text to a refusal that is not exact format
- expected FAILED
- failure_reason INVALID_REFUSAL_FORMAT

**Test 5 exact refusal passes:**

- set raw text to exact refusal string
- expected PASSED
- generation_status NO_EVIDENCE

---

## Persisting Validation Results

Validation results are persisted as an append only Delta dataset.

### Storage Path Used:

```
abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net
/rag/validations/v1/
```

### Validation Table Schema Includes:

- request_id
- run_id
- timestamp_utc
- generation_status
- validation_status
- failure_reason
- citation_count
- uncited_sentence_count
- invalid_anchor_count
- suspicious_new_ids
- refusal_detected
- length_ratio_flag
- validated_citations
- validated_answer_text (only when PASSED)
- model_name
- embedding_model (from trace)
- index_version (from trace)
- policy_version (from trace)

### Write Behavior:

- format delta
- mode append
- schema enforced via StructType
- one record per request_id per run execution

### This Produces a Durable Audit Trail for:

- grounding failures
- refusal correctness
- citation health metrics
- reproducibility of policy and index versions

---

## Response Packaging Contract (R6)

R6 converts internal objects into a public response payload.

### Public Response Must Be:

- stable schema for UI or API clients
- does not expose internal debug structures
- includes request_id, status, answer, citations, token usage, latency

### PublicResponse Fields:

- request_id
- status: OK | NO_EVIDENCE | FAILED
- answer: validated answer text, or empty for FAILED
- citations: list of public citation objects
- token_usage: prompt, completion, total tokens
- latency_ms

---

## Packaging Rules by Status

### FAILED

if validation_status is not PASSED:

- status FAILED
- answer empty
- citations empty
- token_usage filled from llm_result
- latency_ms filled from llm_result

### NO_EVIDENCE

if generation_status is NO_EVIDENCE and validation PASSED:

- status NO_EVIDENCE
- answer is validated_answer_text
- citations empty
- token_usage and latency included

### OK

- status OK
- answer is validated_answer_text
- citations are built by mapping validated_citations to AnswerBundle citation metadata
- only citations that exist in citation_map are included

---

## Citation Object Fields Exposed Publicly:

- anchor
- knowledge_id
- source_reference
- event_date (string or null)
- equipment_id

No internal chunk_text is exposed in public response.

No internal similarity scores are exposed in public response.

This keeps the public payload safe and stable.

---

## Ordering and Determinism in Public Citations

Public citations maintain the order of validated_citations returned by R5.

Since R5 validated_citations must be a subset of AnswerBundle anchors and AnswerBundle anchors are deterministic, the public citations remain stable run to run when inputs are identical.

---

## Observability Captured in This Stage

Fields captured and logged in this stage include:

- request_id
- run_id
- policy_version
- index_version
- embedding_model
- prompt_sha256
- model response_id
- latency_ms
- token usage
- generation_status
- validation_status
- failure_reason
- grounding metrics counts

### This is the Minimum Set Required to Debug:

- prompt drift
- model output regressions
- grounding failures
- cost and latency anomalies

---

## Failure Modes and Recovery Behavior

### Failure Categories Handled:

**R2 input contract failure:**

- fail fast, do not call model
- propagate FAILED

**NO_EVIDENCE due to selection and gating:**

- skip factual answer
- enforce refusal format

**R4 execution transient failures:**

- retry with same prompt
- if retries exhausted, return FAILED

**R5 grounding failures:**

- block output
- persist failure metrics
- return FAILED to public

**Conclusion**

This stage transforms a basic retrieval and generation pipeline into a controlled and production-ready system.

Deterministic chunk selection, stable citation anchors, frozen prompt construction, and fixed execution parameters ensure that identical inputs produce identical outputs. This eliminates non-reproducible behavior and reduces debugging ambiguity.

Post-generation validation enforces grounding by rejecting invented citations, uncited factual statements, and malformed refusal responses. This provides a measurable safety boundary around the language model and prevents unsupported claims from reaching the user.

All validation outcomes are persisted in an append-only Delta dataset, enabling auditability, historical analysis, and policy impact measurement. Model version, index version, and policy version are recorded for each request to maintain traceability across deployments.

Public response packaging enforces a strict separation between internal system metadata and external API contracts. Only validated answer text and approved citation metadata are exposed, preventing accidental leakage of internal structures or intermediate data.

Configuration values such as similarity thresholds and policy limits are versioned and logged. Changes require explicit policy updates rather than silent modifications. This maintains consistency between documentation, code, and runtime behavior.