#search_candidates
import numpy as np
from typing import List, Dict, Any


class SearchError(Exception):
    """Raised when FAISS search fails."""
    pass


def search_candidates(
    *,
    faiss_index,
    query_vector: np.ndarray,
    candidate_k: int
) -> List[Dict[str, Any]]:
    """
    Perform FAISS similarity search to get raw candidate matches.

    Inputs:
    - faiss_index: loaded FAISS index (IndexFlatIP)
    - query_vector: normalized query embedding (1D numpy array)
    - candidate_k: number of candidates to retrieve from FAISS

    Returns:
    - List of candidate dicts with faiss_id and similarity score
    """

    # -------------------------------
    # 1. Prepare query for FAISS
    # -------------------------------
    # FAISS expects shape: (num_queries, dim)
    query_vector = np.expand_dims(query_vector, axis=0)

    # -------------------------------
    # 2. Run FAISS search
    # -------------------------------
    try:
        # scores: inner product similarity scores
        # indices: faiss internal ids
        scores, indices = faiss_index.search(query_vector, candidate_k)
    except Exception as e:
        raise SearchError(f"FAISS search failed: {str(e)}")

    # -------------------------------
    # 3. Extract results
    # -------------------------------
    candidates: List[Dict[str, Any]] = []

    for faiss_id, score in zip(indices[0], scores[0]):
        # FAISS returns -1 when no more neighbors exist
        if faiss_id == -1:
            continue

        candidates.append(
            {
                "faiss_id": int(faiss_id),
                "similarity": float(score),
            }
        )

    # -------------------------------
    # 4. Return raw candidates
    # -------------------------------
    # Ordering is preserved as returned by FAISS (highest similarity first)
    return candidates
