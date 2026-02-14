#ANSWER-ASSMBLY

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import hashlib
import time


ASSEMBLY_CODE_VERSION = "R2_ASSEMBLY_V1"


@dataclass
class AnswerBundle:
    request_id: str
    assembly_status: str  
    answer_text: Optional[str]
    citations: List[Dict[str, Any]]
    used_chunks: List[Dict[str, Any]]
    evidence_block_text: str
    trace: Dict[str, Any]
    assembly_metrics: Dict[str, Any]


def assemble_answer_full_v1(
    retrieval_bundle: Dict[str, Any],
    selection_result,
    policy,
) -> AnswerBundle:

    start_time = time.time()

    request_id = retrieval_bundle["request_id"]

    # Closed-world enforcement + Similarity top gate
    

    if retrieval_bundle["retrieval_status"] != "SUCCESS":
        return _no_evidence_bundle(
            request_id,
            retrieval_bundle,
            policy,
            reason="RETRIEVAL_STATUS_NOT_SUCCESS"
        )

    top_similarity = max(
        [r["similarity"] for r in retrieval_bundle["results"]],
        default=0.0
    )

    if top_similarity < policy.min_top_similarity_score:
        return _no_evidence_bundle(
            request_id,
            retrieval_bundle,
            policy,
            reason="NO_EVIDENCE_LOW_SIMILARITY"
        )

   #Selection status enforcement
    

    if selection_result.selection_status != "OK":
        return _no_evidence_bundle(
            request_id,
            retrieval_bundle,
            policy,
            reason="NO_EVIDENCE_AFTER_SELECTION"
        )

    selected = selection_result.selected_evidence

    if not selected:
        return _no_evidence_bundle(
            request_id,
            retrieval_bundle,
            policy,
            reason="NO_EVIDENCE_EMPTY_SELECTION"
        )

 
    selected = sorted(
        selected,
        key=lambda r: (int(r["rank"]), str(r["chunk_id"]))
    )


    citations = []
    used_chunks = []
    evidence_blocks = []

    for idx, chunk in enumerate(selected):
        anchor = f"C{idx}"

        citation_obj = {
            "chunk_id": chunk["chunk_id"],
            "citation_anchor": anchor,
            "knowledge_id": chunk.get("knowledge_id"),
            "knowledge_type": chunk.get("knowledge_type"),
            "event_date": chunk.get("event_date"),
            "equipment_id": chunk.get("equipment_id"),
            "rank": chunk.get("rank"),
            "similarity": chunk.get("similarity")
        }

        citations.append(citation_obj)

        used_chunks.append({
            "chunk_id": chunk["chunk_id"],
            "rank": chunk["rank"],
            "similarity": chunk["similarity"],
            "chunk_text": chunk["chunk_text"],
            "knowledge_id": chunk.get("knowledge_id"),
            "source_reference": chunk.get("source_reference")

        })

        # Evidence block formatting EXACT per Prompt Contract
        block = (
            f"[{anchor} | chunk_id={chunk['chunk_id']} | "
            f"knowledge_id={chunk.get('knowledge_id')} | "
            f"source={chunk.get('source_reference')}]\n"
            f"{chunk['chunk_text']}\n"
        )

        evidence_blocks.append(block)

    evidence_block_text = "\n".join(evidence_blocks)


    # Assembly Metrics
 

    assembly_metrics = {
        "selected_count": len(selected),
        "dropped_count": len(selection_result.dropped),
        "drop_reasons": [d.reason_code for d in selection_result.dropped],
        "flags": selection_result.flags,
        "top_similarity": top_similarity,
        "assembly_duration_ms": int((time.time() - start_time) * 1000)
    }

    trace = {
        "policy_version": policy.policy_version,
        "assembly_code_version": ASSEMBLY_CODE_VERSION,
        "index_version": retrieval_bundle["index_version"],
        "embedding_model": retrieval_bundle["embedding_model"],
        "retrieval_top_k": retrieval_bundle["top_k"],
        "similarity_threshold": policy.min_top_similarity_score,
        "prompt_template_version": "PROMPT_TEMPLATE_V1"
    }

    return AnswerBundle(
        request_id=request_id,
        assembly_status="OK",
        answer_text=None,
        citations=citations,
        used_chunks=used_chunks,
        evidence_block_text=evidence_block_text,
        trace=trace,
        assembly_metrics=assembly_metrics
    )


def _no_evidence_bundle(request_id, retrieval_bundle, policy, reason):

    return AnswerBundle(
        request_id=request_id,
        assembly_status="NO_EVIDENCE",
        answer_text=None,
        citations=[],
        used_chunks=[],
        evidence_block_text="",
        trace={
            "policy_version": policy.policy_version,
            "assembly_code_version": ASSEMBLY_CODE_VERSION,
            "index_version": retrieval_bundle.get("index_version"),
            "embedding_model": retrieval_bundle.get("embedding_model"),
            "retrieval_top_k": retrieval_bundle.get("top_k"),
            "similarity_threshold": policy.min_top_similarity_score
        },
        assembly_metrics={
            "reason": reason
        }
    )
