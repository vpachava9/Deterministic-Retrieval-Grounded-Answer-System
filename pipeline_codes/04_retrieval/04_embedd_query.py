#embedd_query
import numpy as np


class EmbeddingError(Exception):
    """Raised when query embedding fails."""
    pass


class DimensionMismatchError(Exception):
    """Raised when embedding dimension does not match index."""
    pass


def _l2_normalize(vector: np.ndarray) -> np.ndarray:
    """
    Apply L2 normalization.

    This is REQUIRED because:
    - Index was built using L2-normalized vectors
    - FAISS IndexFlatIP is used
    - Inner product on normalized vectors = cosine similarity
    """
    norm = np.linalg.norm(vector)
    if norm == 0.0:
        raise EmbeddingError("Embedding vector has zero norm")
    return vector / norm


def embed_query(
    *,
    query_text: str,
    manifest: dict,
    embedder_fn
) -> np.ndarray:
    """
    Embed query text into a FAISS-ready vector.

    Inputs:
    - query_text: validated user query text
    - manifest: index manifest loaded in R1.3
    - embedder_fn: callable(text, model_version) -> vector

    Returns:
    - L2-normalized numpy vector ready for FAISS search
    """

    # -------------------------------
    # 1. Read embedding contract from manifest
    # -------------------------------
    embedding_model_version = manifest["embedding_model_version"]
    expected_dim = int(manifest["embedding_dim"])

    # -------------------------------
    # 2. Generate embedding
    # -------------------------------
    try:
        vector = embedder_fn(query_text, embedding_model_version)
    except Exception as e:
        raise EmbeddingError(f"Embedding call failed: {str(e)}")

    vector = np.asarray(vector, dtype=np.float32)

    # -------------------------------
    # 3. Shape and dimension validation
    # -------------------------------
    if vector.ndim != 1:
        raise EmbeddingError("Embedding output must be a 1D vector")

    if vector.shape[0] != expected_dim:
        raise DimensionMismatchError(
            f"Query embedding dim {vector.shape[0]} "
            f"does not match index dim {expected_dim}"
        )

    # -------------------------------
    # 4. Apply L2 normalization (fixed rule)
    # -------------------------------
    vector = _l2_normalize(vector)

    return vector
