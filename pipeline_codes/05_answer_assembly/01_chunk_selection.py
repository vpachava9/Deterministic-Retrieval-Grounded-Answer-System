#chunk_selection.py

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import math
import re



DROP_SIMILARITY_TOP_GATE = "NO_EVIDENCE_LOW_SIMILARITY"
DROP_SIMILARITY_FLOOR = "DROP_SIMILARITY_FLOOR"

DROP_EQUIPMENT_NULL = "DROP_EQUIPMENT_NULL"
DROP_EQUIPMENT_MISMATCH = "DROP_EQUIPMENT_MISMATCH"
DROP_EVENTDATE_NULL = "DROP_EVENTDATE_NULL"
DROP_EVENTDATE_MISMATCH = "DROP_EVENTDATE_MISMATCH"
DROP_KNOWLEDGE_TYPE = "DROP_KNOWLEDGE_TYPE"

DROP_DUP_CHUNK_ID = "DROP_DUP_CHUNK_ID"
DROP_KNOWLEDGE_ID_CAP = "DROP_KNOWLEDGE_ID_CAP"
DROP_OVERLAP = "DROP_OVERLAP"

DROP_EMPTY_TEXT = "DROP_EMPTY_TEXT"
DROP_NOISE_TEXT = "DROP_NOISE_TEXT"
DROP_BUDGET = "DROP_BUDGET"

FLAG_INJECTION_RISK = "INJECTION_RISK"
FLAG_POSSIBLE_CONFLICT = "POSSIBLE_CONFLICT"


@dataclass(frozen=True)
class SelectionPolicy:
    # Similarity gates
    min_top_similarity_score: float  
    min_chunk_similarity_score: float 

    # Limits
    max_chunks: int  # example 6
    max_chunks_per_knowledge_id: int 

    # Token budgets
    max_evidence_tokens: int  
    max_chunk_token_ratio: float 

    # Dedup
    overlap_ratio_threshold: float 

    # Ordering
    ordering_mode: str  

    sanitization_mode: str  

    # Strict refusal if empty
    strict_no_evidence: bool  

    policy_version: str  
    reserved_output_tokens: int


@dataclass
class RequestConstraints:
  
    equipment_id: Optional[str] = None
    event_date_start: Optional[Any] = None  # datetime.date
    event_date_end: Optional[Any] = None    # datetime.date inclusive end, we will treat as inclusive
    knowledge_types: Optional[List[str]] = None  # allowed set if provided


@dataclass
class DropEvent:
    chunk_id: Optional[str]
    rank: Optional[int]
    reason_code: str
    detail: str


@dataclass
class SelectionResult:
    selection_status: str  # "OK" or "NO_EVIDENCE"
    selected_evidence: List[Dict[str, Any]]
    dropped: List[DropEvent]
    flags: List[str]
    metrics: Dict[str, Any]


_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"system prompt",
    r"you are chatgpt",
    r"developer message",
    r"act as",
]

def _normalize_whitespace(s: str) -> str:
    
    s = s.replace("\x00", " ")
    s = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _looks_like_noise(s: str) -> bool:
  
    if not s:
        return True
    letters = sum(ch.isalpha() for ch in s)
    if len(s) >= 200 and letters / max(len(s), 1) < 0.10:
        return True
    if re.search(r"(.)\1{30,}", s):
        return True
    return False

def _has_injection_pattern(s: str) -> bool:
    low = s.lower()
    return any(re.search(p, low) for p in _INJECTION_PATTERNS)

def _token_estimate(s: str) -> int:
  
    if not s:
        return 0
    return len(s.split())

def _overlap_ratio(a: str, b: str) -> float:
    
    # This avoids fragile exact-string compare while staying deterministic.
    def shingles(text: str, k: int = 5) -> set:
        words = text.split()
        if len(words) < k:
            return set([" ".join(words)]) if words else set()
        return set(" ".join(words[i:i+k]) for i in range(len(words) - k + 1))

    sa = shingles(a)
    sb = shingles(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa.intersection(sb))
    union = len(sa.union(sb))
    return inter / union if union else 0.0


# -----------------------------
# Main selection function
# -----------------------------

def select_chunks_v1(
    retrieval_results: List[Dict[str, Any]],
    policy: SelectionPolicy,
    constraints: RequestConstraints
) -> SelectionResult:
    dropped: List[DropEvent] = []
    flags: List[str] = []

    if not retrieval_results:
        return SelectionResult(
            selection_status="NO_EVIDENCE",
            selected_evidence=[],
            dropped=[],
            flags=[],
            metrics={"reason": "EMPTY_RETRIEVAL_RESULTS"}
        )

    # Defensive deterministic sort. Do not trust upstream ordering.
    results = sorted(
        retrieval_results,
        key=lambda r: (int(r.get("rank", 10**9)), str(r.get("chunk_id", "")))
    )

    # Top similarity gate
    top_sim = max(float(r.get("similarity", float("-inf"))) for r in results)
    if not math.isfinite(top_sim) or top_sim < policy.min_top_similarity_score:
        dropped.append(DropEvent(
            chunk_id=None, rank=None,
            reason_code=DROP_SIMILARITY_TOP_GATE,
            detail=f"top_similarity={top_sim}"
        ))
        return SelectionResult(
            selection_status="NO_EVIDENCE",
            selected_evidence=[],
            dropped=dropped,
            flags=flags,
            metrics={"top_similarity": top_sim}
        )

    # Stage A: similarity floor + basic integrity checks + constraint enforcement
    filtered: List[Dict[str, Any]] = []
    for r in results:
        chunk_id = r.get("chunk_id")
        rank = r.get("rank")
        sim = float(r.get("similarity", float("-inf")))
        text = r.get("chunk_text")

        # Similarity floor
        if (not math.isfinite(sim)) or sim < policy.min_chunk_similarity_score:
            dropped.append(DropEvent(chunk_id, rank, DROP_SIMILARITY_FLOOR, f"similarity={sim}"))
            continue

        # Text integrity
        if text is None or not isinstance(text, str):
            dropped.append(DropEvent(chunk_id, rank, DROP_EMPTY_TEXT, "chunk_text is null or not a string"))
            continue

        norm = _normalize_whitespace(text)
        if not norm:
            dropped.append(DropEvent(chunk_id, rank, DROP_EMPTY_TEXT, "chunk_text empty after normalize"))
            continue
        if _looks_like_noise(norm):
            dropped.append(DropEvent(chunk_id, rank, DROP_NOISE_TEXT, "chunk_text flagged as noise"))
            continue

       
        if _has_injection_pattern(norm) and FLAG_INJECTION_RISK not in flags:
            flags.append(FLAG_INJECTION_RISK)

        # knowledge_type enforcement
        if constraints.knowledge_types is not None:
            kt = r.get("knowledge_type")
            if kt not in constraints.knowledge_types:
                dropped.append(DropEvent(chunk_id, rank, DROP_KNOWLEDGE_TYPE, f"knowledge_type={kt}"))
                continue

        # equipment_id enforcement with NULL policy (B)
        if constraints.equipment_id is not None:
            if r.get("equipment_id") is None:
                dropped.append(DropEvent(chunk_id, rank, DROP_EQUIPMENT_NULL, "equipment_id is null under filter"))
                continue
            if str(r.get("equipment_id")) != str(constraints.equipment_id):
                dropped.append(DropEvent(chunk_id, rank, DROP_EQUIPMENT_MISMATCH,
                                         f"equipment_id={r.get('equipment_id')}"))
                continue

        # event_date enforcement with NULL policy (B)
        if constraints.event_date_start is not None or constraints.event_date_end is not None:
            ev = r.get("event_date")
            if ev is None:
                dropped.append(DropEvent(chunk_id, rank, DROP_EVENTDATE_NULL, "event_date is null under date filter"))
                continue
            if constraints.event_date_start is not None and ev < constraints.event_date_start:
                dropped.append(DropEvent(chunk_id, rank, DROP_EVENTDATE_MISMATCH,
                                         f"event_date={ev} < start={constraints.event_date_start}"))
                continue
            if constraints.event_date_end is not None and ev > constraints.event_date_end:
                dropped.append(DropEvent(chunk_id, rank, DROP_EVENTDATE_MISMATCH,
                                         f"event_date={ev} > end={constraints.event_date_end}"))
                continue

        # Keep normalized version for downstream overlap checks and token estimates
        r2 = dict(r)
        r2["_norm_text_for_checks"] = norm
        filtered.append(r2)

    if not filtered:
        return SelectionResult(
            selection_status="NO_EVIDENCE",
            selected_evidence=[],
            dropped=dropped,
            flags=flags,
            metrics={"reason": "ALL_DROPPED_AFTER_FILTERS"}
        )

    # Stage B: dedupe by chunk_id
    seen_chunk: set = set()
    deduped: List[Dict[str, Any]] = []
    for r in filtered:
        cid = r["chunk_id"]
        if cid in seen_chunk:
            dropped.append(DropEvent(cid, r.get("rank"), DROP_DUP_CHUNK_ID, "duplicate chunk_id"))
            continue
        seen_chunk.add(cid)
        deduped.append(r)

    # Stage C: cap by knowledge_id (diversity)
    by_knowledge: Dict[str, int] = {}
    capped: List[Dict[str, Any]] = []
    for r in deduped:
        kid = str(r.get("knowledge_id", ""))
        by_knowledge.setdefault(kid, 0)
        if by_knowledge[kid] >= policy.max_chunks_per_knowledge_id:
            dropped.append(DropEvent(r.get("chunk_id"), r.get("rank"), DROP_KNOWLEDGE_ID_CAP,
                                     f"knowledge_id={kid} cap={policy.max_chunks_per_knowledge_id}"))
            continue
        by_knowledge[kid] += 1
        capped.append(r)

    if not capped:
        return SelectionResult(
            selection_status="NO_EVIDENCE",
            selected_evidence=[],
            dropped=dropped,
            flags=flags,
            metrics={"reason": "ALL_DROPPED_AFTER_KNOWLEDGE_CAP"}
        )

    # Stage D: overlap dedupe (near duplicates)
    overlap_kept: List[Dict[str, Any]] = []
    for r in capped:
        keep = True
        for kept in overlap_kept:
            ratio = _overlap_ratio(r["_norm_text_for_checks"], kept["_norm_text_for_checks"])
            if ratio >= policy.overlap_ratio_threshold:
                dropped.append(DropEvent(r.get("chunk_id"), r.get("rank"), DROP_OVERLAP,
                                         f"overlap_ratio={ratio:.3f} with chunk_id={kept.get('chunk_id')}"))
                keep = False
                break
        if keep:
            overlap_kept.append(r)

    # Stage E: hard max_chunks cap
    overlap_kept = sorted(overlap_kept, key=lambda r: (int(r["rank"]), str(r["chunk_id"])))
    if len(overlap_kept) > policy.max_chunks:
        for r in overlap_kept[policy.max_chunks:]:
            dropped.append(DropEvent(r.get("chunk_id"), r.get("rank"), DROP_BUDGET,
                                     f"exceeded max_chunks={policy.max_chunks}"))
        overlap_kept = overlap_kept[:policy.max_chunks]

    # Stage F: token budget enforcement with per-chunk cap
    evidence_budget = policy.max_evidence_tokens
    per_chunk_cap = int(policy.max_chunk_token_ratio * evidence_budget)

    selected: List[Dict[str, Any]] = []
    used_tokens = 0

    for r in overlap_kept:
        norm = r["_norm_text_for_checks"]
        est = _token_estimate(norm)

        # Enforce per-chunk cap by trimming marker only.
      
        needs_trim = False
        if est > per_chunk_cap:
            needs_trim = True
            est = per_chunk_cap

        # Enforce total evidence budget
        if used_tokens + est > evidence_budget:
            dropped.append(DropEvent(r.get("chunk_id"), r.get("rank"), DROP_BUDGET,
                                     f"budget would exceed max_evidence_tokens={evidence_budget}"))
            continue

        out = {k: v for k, v in r.items() if not k.startswith("_")}
        out["needs_trim"] = needs_trim
        out["reserved_tokens"] = est
        selected.append(out)
        used_tokens += est

    if not selected:
        return SelectionResult(
            selection_status="NO_EVIDENCE",
            selected_evidence=[],
            dropped=dropped,
            flags=flags,
            metrics={"reason": "ALL_DROPPED_AFTER_BUDGETS"}
        )


    nums_by_kid: Dict[str, set] = {}
    for r in selected:
        kid = str(r.get("knowledge_id", ""))
        text = r.get("chunk_text") or ""
        nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", text))
        nums_by_kid.setdefault(kid, set()).update(nums)

    if any(len(v) > 25 for v in nums_by_kid.values()):
        # Overly many numeric values can correlate with conflicting/overloaded evidence.
        if FLAG_POSSIBLE_CONFLICT not in flags:
            flags.append(FLAG_POSSIBLE_CONFLICT)

    metrics = {
        "policy_version": policy.policy_version,
        "top_similarity": top_sim,
        "selected_count": len(selected),
        "dropped_count": len(dropped),
        "used_evidence_tokens_est": used_tokens,
        "evidence_budget": evidence_budget,
        "per_chunk_cap_tokens": per_chunk_cap,
        "knowledge_id_distribution": by_knowledge,
    }

    return SelectionResult(
        selection_status="OK",
        selected_evidence=selected,
        dropped=dropped,
        flags=flags,
        metrics=metrics
    )
