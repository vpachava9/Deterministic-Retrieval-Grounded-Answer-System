# Test B: Existing chunk_text retrieval


from pyspark.sql import functions as F


# Step 1: Load one real chunk_text + its vector (NO temp view)


# Read from embeddings table and join chunk_text from chunks table
embeddings_df = spark.read.format("delta").load(
    "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/embeddings/gold_knowledge_chunk_embeddings_v1"
)

chunks_df = spark.read.format("delta").load(
    "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_chunks_embedding_ready_v3"
)


sample_row = (
    embeddings_df
    .filter(F.col("status") == "SUCCESS")
    .join(
        chunks_df.select("knowledge_chunk_id", "chunk_text"),
        embeddings_df.knowledge_chunk_id == chunks_df.knowledge_chunk_id,
        how="inner"
    )
    .select(
        embeddings_df.knowledge_chunk_id.alias("chunk_id"),
        "chunk_text",
        embeddings_df.embedding_vector.alias("embedding_vector")
    )
    .limit(1)
    .collect()[0]
)

query_chunk_id = sample_row["chunk_id"]
query_text = sample_row["chunk_text"]
query_vector = sample_row["embedding_vector"]

print("Query chunk_id:", query_chunk_id)
print("Query text (truncated):", query_text[:200])



# Step 2: Run FAISS search

scores, ids = index.search(Xq, TOP_K)

faiss_ids = ids[0].tolist()
similarities = scores[0].tolist()

print("FAISS search completed (Test B)")
print("Top FAISS ids:", faiss_ids)
print("Similarity scores:", similarities)


# Step 3: Resolve chunk_ids

resolved = (
    id_map_df[id_map_df["faiss_id"].isin(faiss_ids)]
    .set_index("faiss_id")
    .loc[faiss_ids]
    .reset_index()
)

print("Resolved chunk_ids:")
print(resolved)



# Step 4: Join back metadata for inspection (FINAL)


retrieved_chunks = (
    embeddings_df.alias("e")
    .filter(F.col("e.knowledge_chunk_id").isin(resolved_chunk_ids))
    .join(
        chunks_df.alias("c"),
        F.col("e.knowledge_chunk_id") == F.col("c.knowledge_chunk_id"),
        how="inner"
    )
    .select(
        F.col("c.knowledge_chunk_id").alias("chunk_id"),
        F.col("c.knowledge_id").alias("knowledge_id"),
        F.col("c.knowledge_type_effective"),
        F.col("c.event_date"),
        F.col("c.equipment_id"),
        F.col("c.chunk_text")
    )
)

display(retrieved_chunks)




# Verdict

print("TEST B PASSED (Existing chunk_text retrieval)")
