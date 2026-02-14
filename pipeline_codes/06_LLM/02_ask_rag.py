import uuid
import re
from pyspark.sql import functions as F

def extract_iso_date(question: str):
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", question)
    return m.group(1) if m else None


def infer_knowledge_type(question: str):
    q = question.lower()
    if "quality" in q or "defect" in q:
        return ["QUALITY"]
    if "incident" in q:
        return ["INCIDENT"]
    if "maintenance" in q:
        return ["MAINT"]
    if "sop" in q or "procedure" in q:
        return ["SOP"]
    return None


def normalize_knowledge_type(raw):
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ["maint", "maintenance"]:
        return "MAINT"
    if s in ["incident", "incidents"]:
        return "INCIDENT"
    if s in ["quality", "defect", "defects"]:
        return "QUALITY"
    if s in ["sop", "procedure", "procedures"]:
        return "SOP"
    return s.upper()




def ask_rag(question: str, *, debug: bool = False):

    if not isinstance(question, str) or not question.strip():
        raise ValueError("Question must be non-empty string")

    required_globals = [
        "policy",
        "openai_api_key",
        "faiss_index",
        "chunk_metadata_lookup",
        "index_name",
        "index_version",
        "manifest",
        "retrieve_documents",
        "select_chunks_v1",
        "assemble_answer_full_v1",
        "build_prompt_v1",
        "execute_llm_v1",
        "validate_generation_v1",
        "package_response_v1",
        "spark",
        "RequestConstraints",
    ]
    for g in required_globals:
        if g not in globals():
            raise NameError(f"Global '{g}' not found.")

    request_id = str(uuid.uuid4())

    # SAFETY: do NOT clone global constraints.
    # Build a fresh request-scoped constraints object every time.
    local_constraints = RequestConstraints(
        equipment_id=None,
        event_date_start=None,
        event_date_end=None,
        knowledge_types=None
    )

    # Determine top_k
    if hasattr(policy, "candidate_k"):
        top_k = int(policy.candidate_k)
    elif hasattr(policy, "max_chunks"):
        top_k = int(policy.max_chunks)
    else:
        top_k = 5

    iso_date = extract_iso_date(question)
    inferred_kts = infer_knowledge_type(question)
    if inferred_kts:
        local_constraints.knowledge_types = inferred_kts

    results = []
    router = "vector"


    if iso_date:
        router = "structured_event_date"
        df = spark.table("chunk_with_event_date")

        structured_rows = (
            df.filter(F.col("event_date") == F.to_date(F.lit(iso_date)))
              .select(
                  "knowledge_chunk_id",
                  "knowledge_id",
                  "knowledge_type_effective",
                  "equipment_id",
                  "event_date",
                  "chunk_text",
                  "created_at"
              )
              .orderBy(F.col("created_at").desc())
              .limit(top_k)
              .collect()
        )

        for i, r in enumerate(structured_rows):
            results.append({
                "chunk_id": r["knowledge_chunk_id"],
                "knowledge_id": r["knowledge_id"],
                "knowledge_type": normalize_knowledge_type(r["knowledge_type_effective"]),
                "equipment_id": r["equipment_id"],
                "event_date": r["event_date"],
                "chunk_text": r["chunk_text"],
                "similarity": 1.0,
                "rank": i,
                "source_reference": None
            })


    if not results:
        raw = retrieve_documents(user_question=question, top_k=top_k)

        if not isinstance(raw, list):
            raise TypeError("retrieve_documents must return list")

        if raw and not isinstance(raw[0], dict):
            raw = [r.asDict(recursive=True) for r in raw]

        for i, r in enumerate(raw):
            rr = dict(r)

            if "chunk_id" not in rr:
                raise KeyError("retrieve_documents missing chunk_id")
            if "chunk_text" not in rr:
                raise KeyError("retrieve_documents missing chunk_text")

            rr["knowledge_type"] = normalize_knowledge_type(rr.get("knowledge_type"))
            if "rank" not in rr or rr["rank"] is None:
                rr["rank"] = i
            if "similarity" not in rr:
                rr["similarity"] = float("nan")

            results.append(rr)

    retrieval_bundle = {
        "request_id": request_id,
        "retrieval_status": "SUCCESS" if results else "EMPTY",
        "results": results,
        "retrieval_results": results,
        "index_name": index_name,
        "index_version": index_version,
        "embedding_model": manifest.get("embedding_model", "unknown"),
        "top_k": top_k,
        "router": router,
        "parsed_iso_date": iso_date,
        "knowledge_type_filter": inferred_kts,
    }


    selection_result = select_chunks_v1(
        retrieval_results=results,
        policy=policy,
        constraints=local_constraints
    )

    if selection_result.selection_status != "OK":
        out = {
            "request_id": request_id,
            "status": "NO_EVIDENCE",
            "answer": "NO_EVIDENCE: No valid grounded evidence found.",
            "citations": [],
            "router": router,
        }
        if debug:
            out["selection_result"] = selection_result
            out["retrieval_bundle"] = retrieval_bundle
            out["constraints"] = local_constraints
        return out

    # ---------------------------------------------
    # R3 Assembly
    # ---------------------------------------------
    answer_bundle = assemble_answer_full_v1(
        retrieval_bundle=retrieval_bundle,
        selection_result=selection_result,
        policy=policy
    )


    prompt_result = build_prompt_v1(
        answer_bundle=answer_bundle,
        user_question=question,
        policy=policy
    )


    llm_result = execute_llm_v1(
        request_id=request_id,
        prompt_result=prompt_result,
        policy=policy,
        openai_api_key=openai_api_key
    )

 
    r5_result = validate_generation_v1(
        request_id=request_id,
        llm_result=llm_result,
        answer_bundle=answer_bundle
    )

    if getattr(r5_result, "validation_status", None) != "PASSED":
        out = {
            "request_id": request_id,
            "status": "NO_EVIDENCE",
            "answer": "NO_EVIDENCE: Generated answer failed grounding validation.",
            "citations": [],
            "router": router,
        }
        if debug:
            out["r5_result"] = r5_result
            out["selection_result"] = selection_result
            out["answer_bundle"] = answer_bundle
            out["constraints"] = local_constraints
        return out

    public_response = package_response_v1(
        r5_result=r5_result,
        llm_result=llm_result,
        answer_bundle=answer_bundle
    )

    if not debug:
        return public_response

    return {
        "request_id": request_id,
        "router": router,
        "knowledge_type_filter": inferred_kts,
        "constraints": local_constraints,
        "results_count": len(results),
        "selection_result": selection_result,
        "r5_result": r5_result,
        "public_response": public_response
    }