# Retrieval to Answer Assembly

## Purpose

This stage starts after Retrieval returns a retrieval_bundle.
This stage ends when we have:
1. a deterministic, policy-compliant AnswerBundle
2. a frozen prompt bytes payload ready for LLM execution
3. stable citation anchors that can be validated later
4. strict refusal behavior when evidence is insufficient

This README lists what was implemented and enforced.
It focuses on contracts, checks, invariants, and validation gates.

---

## Stage Boundary

### Input to this stage

- retrieval_bundle (typed schema, not ad hoc dicts)
- user_question (raw user text)
- policy object (frozen values for selection and prompt constraints)
- trace fields needed for audit and reproducibility

### Output of this stage

- AnswerBundle (fixed schema)
- PromptBuildResult (fixed schema)
- LLMExecutionResult (fixed schema, produced by the LLM execution layer)

### Important separation

- Answer Assembly is not just prompt building.
- Prompt builder is only one component inside Answer Assembly.
- Chunk selection happens before prompt building, but after the prompt contract is frozen.

### Correct production order used

1. Answer Assembly Contract
2. Prompt Contract
3. Chunk Selection Rules
4. Prompt Builder Contract
5. LLM Execution Contract
6. Execute end-to-end

---

## R2.0 Answer Assembly Contract

### R2.0A Input Schema Contract (hard contract)

**Rule:**
R2 must receive retrieval_bundle with a fixed schema.
No ad hoc dicts, no missing fields.

**Minimum required fields per retrieval result:**
- chunk_id
- knowledge_id
- chunk_text
- rank
- similarity_score

**Hard fail conditions:**
- any required field missing
- chunk_text is null or empty after sanitization
- rank is missing or not an integer
- similarity_score missing or not a number
- retrieval_bundle is empty without explicitly being treated as NO_EVIDENCE

**Enforcement behavior:**
- if any required field is missing, assembly_status = FAILED
- do not proceed to chunk selection or prompt building when FAILED

### R2.0B Output Schema Contract (hard contract)

**Rule:**
R2 must output answer_bundle with fixed fields.

**AnswerBundle required fields:**
- request_id
- assembly_status (OK, NO_EVIDENCE, FAILED)
- selected_evidence[] where each element includes:
  - chunk_id
  - knowledge_id
  - rank
  - similarity_score
  - citation_anchor
  - sanitized_text
- evidence_block_text (exact bytes used inside prompt)
- trace fields including:
  - index_version
  - policy_version
  - embedding_model
  - retrieval_top_k
  - thresholds used
- assembly_metrics including:
  - token counts
  - dropped counts
  - drop reason codes
  - truncation flags

**Hard fail conditions:**
- missing trace fields
- missing evidence_block_text when assembly_status = OK
- missing citation_anchor mapping when assembly_status = OK

---

## R2.1 Prompt Contract V1 (frozen)

Prompt Contract V1 is frozen before implementing selection rules.
The prompt is required to be structured and deterministic.

### P1 Prompt Structure Contract

**Rule:**
Prompt must always contain the following sections in this exact order:
1. System Instruction Block
2. Safety and Grounding Rules
3. Evidence Block
4. User Question
5. Output Formatting Instructions

**Hard fail conditions:**
- missing any section
- reordering any section
- duplicate section headers

### P2 System Instruction Contract

#### P2.1 Closed world enforcement

**Rule:**
System message must state:
- the model may only use the provided evidence
- the model must not use external knowledge
- if evidence is insufficient, it must refuse

**Refusal string lock:**
The refusal message is frozen as exact text, punctuation, and casing:
```
NO_EVIDENCE: The provided evidence does not contain sufficient information to answer this question.
```

**Hard fail conditions:**
- refusal string differs
- refusal string moved to a different location
- refusal string not present in the system instructions

#### P2.2 No implicit knowledge rule

**Rule:**
The model must not introduce:
- new entities
- new dates
- new numeric values
- procedural steps not present in evidence
- acronym expansions not present in evidence

**Hard fail conditions:**
- any system instruction that permits outside knowledge
- any prompt builder logic that injects extra context not in evidence

### P3 Evidence Block Contract

#### P3.1 Evidence formatting template lock

**Rule:**
Each selected chunk must be rendered using the frozen evidence format:

```
[C{anchor_number} | chunk_id={chunk_id} | knowledge_id={knowledge_id} | source={source_reference}]
{sanitized_chunk_text}
```

**Constraints:**
- anchor_number starts at 0
- anchors must follow the final ordered evidence list
- chunk_text must be sanitized but not rewritten
- no additional metadata beyond allowed fields

**Hard fail conditions:**
- anchor numbering not sequential from 0
- evidence appears before system rules
- evidence contains metadata not allowed
- evidence is rewritten or summarized

#### P3.2 Evidence isolation rule

**Rule:**
Evidence text is untrusted content.
Any instructions inside evidence must be ignored.
Evidence is kept inside a clearly separated evidence section.

**Hard fail conditions:**
- prompt builder merges evidence into system block
- prompt builder allows evidence to alter instruction text

#### P3.3 No evidence mutation

**Rule:**
Evidence chunk_text must not be rewritten, summarized, interpreted, or internally reordered.
Only sanitization is allowed.

**Hard fail conditions:**
- any transformation that changes meaning
- replacing content with a shorter paraphrase

### P4 Citation Contract

#### P4.1 Mandatory citation for factual claims

**Rule:**
Every factual statement must be supported by at least one citation marker in format [C##].

#### P4.2 Citation format lock

**Rule:**
Citation markers in the answer must be in the exact format:
[C0], [C1], [C2], ...

**Hard fail conditions:**
- malformed anchors
- casing mismatch
- brackets missing
- invented anchors not present in allowed set

### P5 Output Formatting Contract

**Rules:**
- provide a clear answer
- every factual claim includes citation markers
- do not include chunk_id or evidence metadata in the answer text
- do not reference the word "Evidence" in the answer
- do not output reasoning traces
- if insufficient evidence exists, output the exact refusal message

**Hard fail conditions:**
- answer includes chunk_id or knowledge_id
- answer includes meta commentary about the system
- answer includes uncited factual content

---

## R2.2 Chunk Selection Rules (policy driven)

Chunk selection only happens after:
- retrieval_bundle input schema validation passes
- prompt contract is frozen
- policy object is loaded

### Selection Policy Snapshot Used

- max_chunks = 6
- max_chunks_per_knowledge_id = 2
- max_evidence_tokens = 2200
- reserved_output_tokens = 800
- max_total_prompt_tokens = 3500
- max_chunk_token_ratio = 0.35
- overlap_ratio_threshold = 0.80
- ordering_mode = rank_strict
- sanitization_mode = safe_normalize_v1
- strict_no_evidence = True
- policy_version = R2_POLICY_V1

### Core Chunk Selection Invariants

**Rank semantics:**
- rank starts at 0
- rank strictly increases
- ordering uses rank as the primary ordering key

**Similarity gates:**
- apply top similarity gate at selection entry
- apply minimum similarity constraints before allowing evidence into prompt
- enforce strict refusal if evidence becomes empty after gating

**Deduplication constraints:**
- overlap-based near-duplicate removal using overlap_ratio_threshold
- keep best ranked chunk when overlap exceeds threshold
- log dropped reasons deterministically

**Diversity constraints:**
- enforce max_chunks_per_knowledge_id cap
- do not drop all chunks from the top document blindly
- apply cap, not single-chunk-only behavior

**Budget constraints:**
- enforce max_evidence_tokens
- enforce max_total_prompt_tokens including reserved output tokens
- prune lowest priority evidence deterministically
- enforce per-chunk cap max_chunk_token_ratio to prevent one chunk dominating

**Ordering constraints:**
ordering_mode = rank_strict
- primary: rank ascending
- tie break: chunk_id ascending
- never rely on partition order or non-deterministic list order

**NO_EVIDENCE semantics:**
- if selected_evidence becomes empty after pruning, dedupe, sanitization, or filtering:
  - assembly_status = NO_EVIDENCE
  - do not build prompt
  - do not call LLM

### Selection Outputs and Metrics Captured

**Selection output fields included in AnswerBundle.selected_evidence[]:**
- chunk_id
- knowledge_id
- rank
- similarity_score
- citation_anchor (assigned later, after ordering frozen)
- sanitized_text (sanitized but not rewritten)

**Selection metrics recorded in assembly_metrics:**
- retrieved_k
- selected_k
- dedup_dropped_count
- budget_dropped_count
- per_knowledge_cap_dropped_count
- evidence_token_count
- truncation_applied true or false
- drop reason codes

**Drop reason codes tracked:**
Examples of drop reason categories:
- DROP_DUP
- DROP_BUDGET
- DROP_PER_KNOWLEDGE_CAP
- DROP_EMPTY_AFTER_SANITIZE
- DROP_BELOW_SIMILARITY_FLOOR

**Hard failure behavior:**
- if any hard selection invariant fails, assembly_status = FAILED
- downstream prompt build is blocked

---

## R2.3 Sanitization and Evidence Integrity Checks

### Sanitization Mode Used

sanitization_mode = safe_normalize_v1

### Sanitization Operations Applied to chunk_text

- remove null bytes
- remove control characters
- normalize whitespace
- preserve semantics
- do not rewrite content

### Post-Sanitization Integrity Checks

- if a chunk becomes empty after sanitization, drop it
- if all chunks drop, return NO_EVIDENCE
- record drop counts and reasons

**Hard fail conditions:**
- sanitization rewrites meaning
- sanitization produces evidence that breaks prompt structure

---

## R2.4 Citation Anchor Assignment

### Anchor Numbering Rule

- anchors are assigned after final evidence ordering is frozen
- anchor = C{index} where index is the position in the final ordered list
- first chunk gets C0, second gets C1, etc

### Anchor Mapping Object Created

- anchor_map maps each anchor to chunk_id
- used later by post-generation validation

**Hard fail conditions:**
- anchor order does not match evidence order
- anchor map missing any selected evidence chunk

---

## R2.5 Evidence Block Construction

### Evidence Block Rendering Contract

For each selected chunk, render exactly:
```
[C{anchor} | chunk_id=... | knowledge_id=... | source=...]
<sanitized_text>
```

**Constraints:**
- no deviation in bracket format
- no additional metadata fields allowed
- evidence block text is recorded as exact bytes
- evidence_block_text must be stable for replay and audit

### Token Tracking During Evidence Rendering

- estimate evidence tokens incrementally
- stop adding evidence when max_evidence_tokens would be exceeded
- log reason DROP_BUDGET when pruning occurs
- ensure evidence tokens plus reserved output fit total budget

**Hard fail conditions:**
- evidence block exceeds budget without pruning
- evidence block is built when assembly_status is NO_EVIDENCE

---

## R2.6 Prompt Builder Contract and Prompt Determinism

### PB1 Order Lock and Static Section Injection

**Rule:**
Insert the frozen sections in the frozen order:
- system block
- safety block
- evidence header
- evidence block text
- question header
- question text
- output requirements block

**Constraints:**
- section order cannot change
- headers cannot change
- no hidden sections allowed

### PB2 Question Injection Rules

- user_question is inserted exactly as received
- no rewriting
- no paraphrasing
- only whitespace normalization allowed

### PB3 Token Allocation Split

**Token budgets reserved:**
- system + safety block: fixed budget
- evidence block: capped by max_evidence_tokens
- question block: capped
- reserved_output_tokens reserved for the model response

**Hard fail conditions:**
- evidence consumes output token reserve
- prompt exceeds max_total_prompt_tokens

### PB4 Final Token Budget Validation

**Compute:**
```
total_prompt_tokens =
  system_tokens +
  safety_tokens +
  evidence_tokens +
  question_tokens +
  reserved_output_tokens
```

If total exceeds max_total_prompt_tokens:
- drop lowest ranked chunk
- rebuild evidence block deterministically
- repeat until valid

### PB5 Byte Determinism Requirements

Given identical inputs:
- retrieval_bundle
- selected_evidence
- policy
- user_question

The constructed prompt must be byte-identical.

**Hard fail conditions:**
- prompt text differs for identical inputs
- prompt builder injects timestamp, random id, or non-deterministic whitespace

---

## R2.7 Prompt Builder Validation Tests (smoke tests for determinism and safety)

### Test 1 Basic Correctness

- prompt builds with expected sections and evidence formatting

### Test 2 Deterministic Reproducibility

- same bundle and question produce identical prompt bytes

### Test 3 Hard Budget Enforcement

- evidence prunes deterministically when budgets are exceeded

### Test 4 Refusal Semantics Preserved

- when AnswerBundle is NO_EVIDENCE, prompt builder returns build_status = NO_EVIDENCE and empty prompt_text

### Test 5 Injection Safety

- if evidence contains malicious instruction text, system block appears first
- malicious text remains inside evidence section only
- system rules appear before any malicious text

**Hard fail conditions:**
- any test fails blocks moving to LLM execution

---

## R3 LLM Execution Contract V1 (execution wrapper)

This layer sends the exact prompt bytes to the model without mutation.
It is treated as a thin wrapper that must not modify upstream behavior.

### Model Target Frozen

- model family frozen for Prompt Template V1 usage
- model identity must be logged

### Execution Behavior Rules

- send exact prompt bytes as built
- do not append additional instructions
- do not switch models on failure
- do not parse or edit model output here
- only retry transient failures
- retries must reuse the exact same prompt bytes

### Telemetry Captured in LLMExecutionResult Schema

- request_id
- model_name
- prompt_sha256
- generation_status (OK, FAILED)
- raw_model_text
- finish_reason
- attempts
- llm_latency_ms
- prompt_tokens_actual
- completion_tokens_actual
- total_tokens_actual

### Safety and Compliance Logging Rule

- avoid logging full prompt text in plain logs if content may be sensitive
- prefer hashing plus token stats for auditability

---

## R5 Post-Generation Validation Entry Point (downstream dependency)

This stage is downstream, but Answer Assembly produces the artifacts it needs.

### Artifacts Produced in This Stage for R5

- stable citation anchors
- anchor map
- evidence block text bytes
- prompt hash
- allowed anchor set

### R5 Contracts Referenced for Completeness

**R5 output schema frozen:**
- generation_status: OK | FAILED | NO_EVIDENCE
- validation_status: PASSED | FAILED
- failure_reason: string or null
- validated_answer_text
- validated_citations
- grounding_metrics

**Core validation checks expected in R5:**
- citation extraction regex: \[C\d+\]
- allowed anchor set enforcement
- sentence grounding rule: every factual sentence must include citation
- refusal exact match enforcement
- fail closed behavior: no silent acceptance

---

## Failure Behavior Summary

### Hard Fail Conditions that Return FAILED

- missing required retrieval input fields
- invalid rank semantics
- missing similarity_score
- missing trace fields
- prompt structure not matching frozen contract
- evidence formatting deviates from template
- prompt exceeds token budgets and cannot be repaired deterministically
- determinism tests fail

### NO_EVIDENCE Behavior

- if selected evidence becomes empty after gates, sanitization, or budgets
- assembly_status = NO_EVIDENCE
- prompt build is skipped
- LLM call is skipped
- refusal string is the only allowed user-facing response

### OK Behavior

- stable selected_evidence produced
- stable evidence_block_text bytes produced
- stable anchor map produced
- prompt bytes built deterministically
- LLM execution wrapper called with exact prompt bytes

---

## Related Code Files in This Stage

### Answer Assembly and Selection

- chunk_selection.py
- answer_assembly_contracts.py
- policy.py

### Prompt Contract and Builder

- prompt_contract_v1.py
- prompt_builder_v1.py
- prompt_template_v1.txt (frozen literal template text)

### LLM Execution Wrapper

- llm_execution_v1.py

### Post-Generation Validation Dependency Artifacts Produced Here

- post_validator.py (downstream, consumes anchors and prompt hash)