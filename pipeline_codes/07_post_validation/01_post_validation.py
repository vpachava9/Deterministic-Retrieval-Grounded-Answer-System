# rag/post_generation_validator.py

from dataclasses import dataclass
from typing import Dict, List, Optional, Set
import re



INVALID_CITATION_REFERENCE = "INVALID_CITATION_REFERENCE"
UNCITED_FACTUAL_STATEMENT = "UNCITED_FACTUAL_STATEMENT"
INVALID_REFUSAL_FORMAT = "INVALID_REFUSAL_FORMAT"
POSSIBLE_EXTERNAL_KNOWLEDGE = "POSSIBLE_EXTERNAL_KNOWLEDGE"
NO_CITATIONS_PRESENT = "NO_CITATIONS_PRESENT"
CITATION_MISMATCH = "CITATION_MISMATCH"


REFUSAL_EXACT = (
    "NO_EVIDENCE: The provided evidence does not contain sufficient information to answer this question."
)


CITATION_REGEX = re.compile(r"\[C\d+\]")
ANCHOR_REGEX = re.compile(r"C(\d+)")
DATE_REGEX = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
ID_TOKEN_REGEX = re.compile(r"\b[A-Za-z0-9_]{8,}\b")


FACT_ACTION_VERBS = {
    "performed", "replaced", "adjusted", "verified",
    "calibrated", "installed", "removed", "returned",
    "addressed", "fixed", "repaired", "changed"
}

SUSPICIOUS_PREFIXES = ("EQ_", "LINE_", "MAINT_", "SOP_")



@dataclass
class R5ValidationResult:
    request_id: str
    generation_status: str
    validation_status: str
    failure_reason: Optional[str]
    validated_answer_text: str
    validated_citations: List[str]
    grounding_metrics: Dict[str, object]



def _split_units(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    parts = re.split(r"\n(?=\s*\d+\.)", text)
    units = []

    for p in parts:
        p = p.strip()
        if not p:
            continue
        subparts = re.split(r"\n\s*\n", p)
        for sp in subparts:
            sp = sp.strip()
            if sp:
                units.append(sp)

    return units


def _contains_fact(text: str) -> bool:
    s = text.lower()

    if DATE_REGEX.search(text):
        return True

    words = re.findall(r"[a-zA-Z_]+", s)
    if any(w in FACT_ACTION_VERBS for w in words):
        return True

    if "eq_" in s or "line_" in s:
        return True

    return False


def _extract_citations(text: str) -> List[str]:
    return CITATION_REGEX.findall(text or "")


def _extract_anchor_ids(citations: List[str]) -> List[int]:
    ids = []
    for c in citations:
        m = ANCHOR_REGEX.search(c)
        if m:
            ids.append(int(m.group(1)))
    return ids


def _allowed_anchors(bundle) -> Set[str]:
    allowed = set()
    for c in getattr(bundle, "citations", []):
        if isinstance(c, dict):
            anchor = c.get("citation_anchor")
            if anchor:
                allowed.add(anchor)
    return allowed


def _allowed_entities(bundle) -> Set[str]:
    entities = set()

    for c in getattr(bundle, "citations", []):
        if isinstance(c, dict):
            for key in ["knowledge_id", "equipment_id", "event_date", "knowledge_type"]:
                v = c.get(key)
                if v is not None:
                    entities.add(str(v))

    evidence_text = getattr(bundle, "evidence_block_text", "") or ""
    for tok in ID_TOKEN_REGEX.findall(evidence_text):
        entities.add(tok)

    return entities


def _suspicious_tokens(text: str) -> List[str]:
    toks = set(ID_TOKEN_REGEX.findall(text or ""))
    return sorted([t for t in toks if any(p in t for p in SUSPICIOUS_PREFIXES)])



def validate_generation_v1(
    request_id: str,
    llm_result,
    answer_bundle,
) -> R5ValidationResult:

    raw_text = (getattr(llm_result, "raw_model_text", "") or "").strip()
    gen_status = getattr(llm_result, "generation_status", None)

    # Generation checks
 
    if gen_status == "NO_EVIDENCE":
        return R5ValidationResult(
            request_id, "NO_EVIDENCE", "PASSED", None, "",
            [], {
                "citation_count": 0,
                "uncited_sentence_count": 0,
                "invalid_anchor_count": 0,
                "refusal_detected": True,
                "length_ratio_flag": False
            }
        )

    if gen_status != "OK":
        return R5ValidationResult(
            request_id, "FAILED", "FAILED", "GENERATION_NOT_OK",
            "", [], {
                "citation_count": 0,
                "uncited_sentence_count": 0,
                "invalid_anchor_count": 0,
                "refusal_detected": False,
                "length_ratio_flag": False
            }
        )

    #Refusal enforcement

    if raw_text.startswith("NO_EVIDENCE:") and raw_text != REFUSAL_EXACT:
        return R5ValidationResult(
            request_id, "FAILED", "FAILED", INVALID_REFUSAL_FORMAT,
            "", [], {
                "citation_count": 0,
                "uncited_sentence_count": 0,
                "invalid_anchor_count": 0,
                "refusal_detected": True,
                "length_ratio_flag": False
            }
        )

    if raw_text == REFUSAL_EXACT:
        return R5ValidationResult(
            request_id, "NO_EVIDENCE", "PASSED", None,
            REFUSAL_EXACT, [], {
                "citation_count": 0,
                "uncited_sentence_count": 0,
                "invalid_anchor_count": 0,
                "refusal_detected": True,
                "length_ratio_flag": False
            }
        )


    citations = _extract_citations(raw_text)
    if not citations:
        return R5ValidationResult(
            request_id, "FAILED", "FAILED", NO_CITATIONS_PRESENT,
            "", [], {
                "citation_count": 0,
                "uncited_sentence_count": 0,
                "invalid_anchor_count": 0,
                "refusal_detected": False,
                "length_ratio_flag": False
            }
        )

    unique = sorted(set(citations), key=lambda x: int(ANCHOR_REGEX.search(x).group(1)))
    anchor_ids = _extract_anchor_ids(unique)
    cited_anchors = {f"C{i}" for i in anchor_ids}

    allowed = _allowed_anchors(answer_bundle)
    invalid = sorted([a for a in cited_anchors if a not in allowed])

    if invalid:
        return R5ValidationResult(
            request_id, "FAILED", "FAILED", INVALID_CITATION_REFERENCE,
            "", [], {
                "citation_count": len(unique),
                "uncited_sentence_count": 0,
                "invalid_anchor_count": len(invalid),
                "invalid_anchors": invalid,
                "refusal_detected": False,
                "length_ratio_flag": False
            }
        )


    units = _split_units(raw_text)
    violations = []

    for u in units:
        if not _contains_fact(u):
            continue

        citation_matches = list(CITATION_REGEX.finditer(u))

        # If factual unit has no citation → fail
        if not citation_matches:
            violations.append(u)
            continue

        # Ensure no factual text appears AFTER last citation
        last = citation_matches[-1]
        after_text = u[last.end():]

        if _contains_fact(after_text):
            violations.append(after_text)

    if violations:
        return R5ValidationResult(
            request_id, "FAILED", "FAILED", UNCITED_FACTUAL_STATEMENT,
            "", [], {
                "citation_count": len(unique),
                "uncited_sentence_count": len(violations),
                "invalid_anchor_count": 0,
                "example_uncited_sentence": violations[0][:200],
                "refusal_detected": False,
                "length_ratio_flag": False
            }
        )

    allowed_entities = _allowed_entities(answer_bundle)
    suspicious = _suspicious_tokens(raw_text)

    external = [tok for tok in suspicious if tok not in allowed_entities]

    if external:
        return R5ValidationResult(
            request_id, "FAILED", "FAILED", POSSIBLE_EXTERNAL_KNOWLEDGE,
            "", [], {
                "citation_count": len(unique),
                "uncited_sentence_count": 0,
                "invalid_anchor_count": 0,
                "suspicious_new_ids": external[:10],
                "refusal_detected": False,
                "length_ratio_flag": False
            }
        )

  
    return R5ValidationResult(
        request_id, "OK", "PASSED", None,
        raw_text,
        [f"C{i}" for i in sorted(set(anchor_ids))],
        {
            "citation_count": len(unique),
            "uncited_sentence_count": 0,
            "invalid_anchor_count": 0,
            "refusal_detected": False,
            "length_ratio_flag": False
        }
    )
