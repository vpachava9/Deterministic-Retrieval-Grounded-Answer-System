#Resolve_and_join
from pyspark.sql import functions as F

class ResolutionError(Exception):
    pass


def resolve_and_join(candidates, id_map, metadata_df):
    """
    Resolve FAISS ids → chunk metadata.

    Contracts:
    - id_map: {faiss_id (int) → chunk_id (int)}
    - chunk_df.chunk_id: INT
    """

    # 1. Resolve FAISS ids → chunk_id
    resolved_rows = []

    for rank, c in enumerate(candidates):
        faiss_id = c["faiss_id"]

        if faiss_id not in id_map:
            raise ResolutionError(f"faiss_id {faiss_id} missing in id_map")

        resolved_rows.append(
            (
                rank,
                faiss_id,
                id_map[faiss_id],   # numeric chunk_id
                float(c["similarity"])
            )
        )

    resolved_df = spark.createDataFrame(
        resolved_rows,
        ["rank", "faiss_id", "chunk_id", "similarity"]
    )

    # 2. Join with chunk metadata using chunk_id
    joined_df = (
        resolved_df
        .join(metadata_df, on="chunk_id", how="left")
    )

    # 3. Post-join validation
    missing = joined_df.filter(F.col("knowledge_id").isNull()).count()

    if missing > 0:
        raise ResolutionError(
            f"{missing} chunks missing after join"
        )

    # 4. Preserve FAISS rank order
    ordered_df = joined_df.orderBy("rank")

    return ordered_df.collect()
