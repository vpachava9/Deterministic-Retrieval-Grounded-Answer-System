semantic_v2 = chunks_df.join(
    corrupted_chunks.select("knowledge_chunk_id"),
    on="knowledge_chunk_id",
    how="left_anti"
)

semantic_v2.write.format("delta").mode("overwrite").save(semantic_v2_path)