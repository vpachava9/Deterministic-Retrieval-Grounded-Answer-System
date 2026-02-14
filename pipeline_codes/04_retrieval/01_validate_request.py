# validate_request.py

import uuid
import hashlib
import re
from datetime import date
from typing import Dict, Any


class ValidationError(Exception):
    pass


def _is_query_quality_ok(query_text: str, config: dict) -> bool:
    """
    Lightweight lexical quality gate.
    Blocks junk / keyboard smash / meaningless queries.
    """

    q = query_text.strip()

    if not q:
        return False

    if len(q) < config["thresholds"]["min_query_chars"]:
        return False

    tokens = re.findall(r"[A-Za-z0-9]+", q)
    if len(tokens) < config["thresholds"]["min_query_tokens"]:
        return False

    alpha_tokens = [t for t in tokens if re.search(r"[A-Za-z]", t)]
    alpha_ratio = len(alpha_tokens) / max(len(tokens), 1)

    if alpha_ratio < config["thresholds"]["min_alpha_token_ratio"]:
        return False

    if re.search(r"(.)\1{5,}", q):
        return False

    return True


def validate_request(raw_request: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize a raw retrieval request.
    """

    # -------------------------------
    # 1. request_id
    # -------------------------------
    request_id = raw_request.get("request_id") or str(uuid.uuid4())
    if not isinstance(request_id, str) or len(request_id) > 64:
        raise ValidationError("Invalid request_id")

    # -------------------------------
    # 2. query_text
    # -------------------------------
    query_text = raw_request.get("query_text")
    if not isinstance(query_text, str):
        raise ValidationError("query_text must be a string")

    query_text = query_text.strip()
    if not query_text:
        raise ValidationError("query_text cannot be empty")

    if len(query_text) > config["limits"]["max_query_length_chars"]:
        raise ValidationError("query_text exceeds maximum allowed length")

    # Query quality gate
    if not _is_query_quality_ok(query_text, config):
        raise ValidationError(
            "query_text failed quality gate (likely junk or OOD input)"
        )

    # -------------------------------
    # 3. index_name
    # -------------------------------
    index_name = raw_request.get("index_name")
    if not isinstance(index_name, str) or not index_name.strip():
        raise ValidationError("index_name is required")
    index_name = index_name.strip()

    # -------------------------------
    # 4. index_version
    # -------------------------------
    index_version = raw_request.get("index_version")
    if not isinstance(index_version, str) or not index_version.strip():
        raise ValidationError("index_version is required")
    index_version = index_version.strip()

    if index_version.lower() in {"latest", "current", "default"}:
        raise ValidationError("index_version must be immutable")

    # -------------------------------
    # 5. top_k
    # -------------------------------
    top_k = raw_request.get("top_k", config["defaults"]["top_k"])
    if not isinstance(top_k, int):
        raise ValidationError("top_k must be an integer")
    if top_k < 1 or top_k > config["limits"]["max_top_k"]:
        raise ValidationError("top_k out of range")

    candidate_k = top_k * config["defaults"]["candidate_multiplier"]

    # -------------------------------
    # 6. filters
    # -------------------------------
    raw_filters = raw_request.get("filters", {}) or {}
    if not isinstance(raw_filters, dict):
        raise ValidationError("filters must be an object")

    filters: Dict[str, Any] = {}

    if "knowledge_type_effective" in raw_filters:
        kt = raw_filters["knowledge_type_effective"]
        if isinstance(kt, str):
            kt = [kt]
        if not isinstance(kt, list) or not kt:
            raise ValidationError("knowledge_type_effective must be non-empty")
        filters["knowledge_type_effective"] = [x.strip() for x in kt]

    if "equipment_id" in raw_filters:
        eq = raw_filters["equipment_id"]
        if isinstance(eq, list):
            filters["equipment_id"] = [x.strip() for x in eq if x.strip()]
        elif isinstance(eq, str) and eq.strip():
            filters["equipment_id"] = [eq.strip()]
        else:
            raise ValidationError("equipment_id invalid")

    start_date = raw_filters.get("event_date_start")
    end_date = raw_filters.get("event_date_end")
    if start_date or end_date:
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise ValidationError("event_date filters must be dates")
        if start_date > end_date:
            raise ValidationError("event_date_start > event_date_end")
        filters["event_date_start"] = start_date
        filters["event_date_end"] = end_date

    # -------------------------------
    # 7. similarity override
    # -------------------------------
    min_similarity_override = raw_request.get("min_similarity_override")
    if min_similarity_override is not None:
        if not isinstance(min_similarity_override, (float, int)):
            raise ValidationError("min_similarity_override must be numeric")
        if not (0.0 <= float(min_similarity_override) <= 1.0):
            raise ValidationError("min_similarity_override out of range")

    # -------------------------------
    # 8. query hash
    # -------------------------------
    query_hash = hashlib.sha256(query_text.encode("utf-8")).hexdigest()

    # -------------------------------
    # 9. validated request
    # -------------------------------
    return {
        "request_id": request_id,
        "query_text": query_text,
        "query_text_hash": query_hash,
        "index_name": index_name,
        "index_version": index_version,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "filters": filters,
        "min_similarity_override": min_similarity_override,
    }
