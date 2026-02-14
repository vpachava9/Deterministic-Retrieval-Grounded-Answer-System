# apply_filters_and_threshold.py

class RetrievalEmptyError(Exception):
    pass


class RetrievalContractError(Exception):
    pass


def apply_filters_and_threshold(
    resolved_results,
    validated_request,
    config
):
    """
    Apply strict metadata filters, similarity thresholds,
    semantic validity gates, and top_k truncation.

    Input: Spark Row objects
    Output: List[Row]
    """

    # -------------------------------
    # 0. Resolve similarity threshold safely
    # -------------------------------
    if (
        "min_similarity_override" in validated_request
        and validated_request["min_similarity_override"] is not None
    ):
        min_similarity = float(validated_request["min_similarity_override"])
    else:
        min_similarity = float(config["thresholds"]["min_similarity"])

    # -------------------------------
    # 1. Metadata filters (STRICT)
    # -------------------------------
    filtered = resolved_results
    filters = validated_request["filters"]

    if "knowledge_type_effective" in filters:
        allowed = set(filters["knowledge_type_effective"])
        filtered = [
            r for r in filtered
            if r["knowledge_type_effective"] in allowed
        ]

    if "equipment_id" in filters:
        allowed = set(filters["equipment_id"])
        filtered = [
            r for r in filtered
            if r["equipment_id"] in allowed
        ]

    if "event_date_start" in filters and "event_date_end" in filters:
        start = filters["event_date_start"]
        end = filters["event_date_end"]
        filtered = [
            r for r in filtered
            if r["event_date"] is not None
            and start <= r["event_date"] <= end
        ]

    # -------------------------------
    # 2. Similarity threshold
    # -------------------------------
    filtered2 = []
    for r in filtered:
        sim = r["similarity"]
        if sim is None:
            raise RetrievalContractError(
                "Resolved row missing similarity score"
            )
        if sim >= min_similarity:
            filtered2.append(r)

    if not filtered2:
        raise RetrievalEmptyError(
            "No chunks meet similarity and filter criteria"
        )

    # -------------------------------
    # 3. Semantic validity gate (OOD protection)
    # -------------------------------
    strong_floor = float(config["thresholds"]["strong_similarity_floor"])
    min_strong_hits = int(config["thresholds"]["min_strong_hits"])

    strong_hits = [
        r for r in filtered2
        if r["similarity"] >= strong_floor
    ]

    if len(strong_hits) < min_strong_hits:
        raise RetrievalEmptyError(
            "Query failed semantic validity check (likely OOD input)"
        )

    # -------------------------------
    # 4. Similarity spread gate
    # -------------------------------
    if len(filtered2) >= 2:
        top_sim = filtered2[0]["similarity"]
        second_sim = filtered2[1]["similarity"]

        max_gap = float(config["thresholds"]["max_similarity_gap"])
        if (top_sim - second_sim) > max_gap:
            raise RetrievalEmptyError(
                "Query failed similarity distribution check (likely OOD)"
            )

    # -------------------------------
    # 5. Enforce top_k
    # -------------------------------
    top_k = int(validated_request["top_k"])
    return filtered2[:top_k]

config = {
    "paths": {
        "faiss_index_root": "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/vector_index/faiss",
        "local_index_cache": "/dbfs/tmp/index_cache"
    },

    "thresholds": {
        # Query validation
        "min_query_chars": 10,
        "min_query_tokens": 2,
        "min_alpha_token_ratio": 0.6,

        # Retrieval similarity
        "min_similarity": 0.76,
        "strong_similarity_floor": 0.50,
        "min_strong_hits": 1,
        "max_similarity_gap": 0.40
    },

    "limits": {
        "max_query_length_chars": 500,
        "max_top_k": 20
    },

    "defaults": {
        "top_k": 5,
        "candidate_multiplier": 5
    }
}
