# rag/response_packager.py

from dataclasses import dataclass
from typing import Dict, Any, List, Optional


@dataclass
class PublicResponse:
    request_id: str
    status: str
    answer: str
    citations: List[Dict[str, Any]]
    token_usage: Dict[str, Optional[int]]
    latency_ms: Optional[int]


def package_response_v1(
    r5_result,
    llm_result,
    answer_bundle
) -> PublicResponse:

    request_id = r5_result.request_id

    if r5_result.validation_status != "PASSED":
        return PublicResponse(
            request_id=request_id,
            status="FAILED",
            answer="",
            citations=[],
            token_usage={
                "prompt_tokens": llm_result.prompt_tokens_actual,
                "completion_tokens": llm_result.completion_tokens_actual,
                "total_tokens": llm_result.total_tokens_actual
            },
            latency_ms=llm_result.llm_latency_ms
        )


    if r5_result.generation_status == "NO_EVIDENCE":
        return PublicResponse(
            request_id=request_id,
            status="NO_EVIDENCE",
            answer=r5_result.validated_answer_text,
            citations=[],
            token_usage={
                "prompt_tokens": llm_result.prompt_tokens_actual,
                "completion_tokens": llm_result.completion_tokens_actual,
                "total_tokens": llm_result.total_tokens_actual
            },
            latency_ms=llm_result.llm_latency_ms
        )


    citation_map = {
        c["citation_anchor"]: c
        for c in answer_bundle.citations
    }

    public_citations = []

    for anchor in r5_result.validated_citations:
        c = citation_map.get(anchor)
        if c:
            public_citations.append({
                "anchor": anchor,
                "knowledge_id": c.get("knowledge_id"),
                "source_reference": c.get("source_reference"),
                "event_date": str(c.get("event_date")) if c.get("event_date") else None,
                "equipment_id": c.get("equipment_id")
            })

    return PublicResponse(
        request_id=request_id,
        status="OK",
        answer=r5_result.validated_answer_text,
        citations=public_citations,
        token_usage={
            "prompt_tokens": llm_result.prompt_tokens_actual,
            "completion_tokens": llm_result.completion_tokens_actual,
            "total_tokens": llm_result.total_tokens_actual
        },
        latency_ms=llm_result.llm_latency_ms
    )
