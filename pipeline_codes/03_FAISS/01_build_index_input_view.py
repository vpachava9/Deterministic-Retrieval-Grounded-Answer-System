# Build_index_input_view.py
# Purpose: Build index-input view for FAISS vector search prototype.


from pyspark.sql import functions as F

CHUNKS_PATH = "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_chunks_embedding_ready_v3"
KNOWLEDGE_PATH = "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_assets"
EMBEDDINGS_PATH = "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/embeddings/gold_knowledge_chunk_embeddings_v1"

EXPECTED_MODEL_NAME = "text-embedding-3-large"
EXPECTED_MODEL_VERSION = "embed_ops_v1"  
EXPECTED_DIM = 3072

INDEX_INPUT_VIEW = "vw_vector_index_input_v1"

chunks_df = spark.read.format("delta").load(CHUNKS_PATH)
knowledge_df = spark.read.format("delta").load(KNOWLEDGE_PATH)
embeddings_df = spark.read.format("delta").load(EMBEDDINGS_PATH)

# -----------------------
# Step 1: Filter chunks first (eligibility)
# -----------------------
chunks_filtered = (
    chunks_df
    .filter(F.col("is_quarantined") == F.lit(False))
    .filter(F.col("eligible_at").isNotNull())
)

# Project only needed chunk columns and rename to avoid collisions
c = (
    chunks_filtered.select(
        F.col("knowledge_chunk_id").alias("c_chunk_id"),
        F.col("knowledge_id").alias("c_knowledge_id"),
        F.col("knowledge_type_effective").alias("c_knowledge_type"),
        F.col("chunk_index").alias("chunk_index"),
        F.col("chunk_text").alias("chunk_text"),
        F.col("chunk_token_count").alias("chunk_token_count"),
        F.col("created_at").alias("created_at"),
        F.col("pipeline_run_id").alias("chunk_pipeline_run_id")
    )
)

# -----------------------
# Step 2: Filter embeddings second (SUCCESS + model pinning)
# -----------------------
embeddings_filtered = (
    embeddings_df
    .filter(F.col("status") == F.lit("SUCCESS"))
    .filter(F.col("embedding_vector").isNotNull())
    .filter(F.col("embedding_dimension") == F.lit(EXPECTED_DIM))
    .filter(F.col("embedding_model_name") == F.lit(EXPECTED_MODEL_NAME))
    .filter(F.col("embedding_model_version") == F.lit(EXPECTED_MODEL_VERSION))
)

# Project only needed embedding columns and rename
e = (
    embeddings_filtered.select(
        F.col("knowledge_chunk_id").alias("e_chunk_id"),
        F.col("knowledge_id").alias("e_knowledge_id"),
        F.col("embedding_vector").alias("embedding_vector"),
        F.col("embedding_dimension").alias("embedding_dim"),
        F.col("embedding_model_name").alias("embedding_model_name"),
        F.col("embedding_model_version").alias("embedding_model_version"),
        F.col("chunk_text_hash").alias("chunk_text_hash"),
        F.col("embedded_at").alias("embedded_at"),
        F.col("pipeline_run_id").alias("embedding_run_id")
    )
)

# -----------------------
# Step 3: Join embeddings to chunks (inner only)
# -----------------------
ec = (
    e.join(c, on=F.col("e_chunk_id") == F.col("c_chunk_id"), how="inner")
)

# Enforce join integrity expectation: knowledge_id should match across embeddings and chunks

ec = ec.withColumn("knowledge_id_mismatch", F.col("e_knowledge_id") != F.col("c_knowledge_id"))

# Choose authoritative knowledge_id (chunks and embeddings should match; pick embeddings for consistency with stored vectors)
ec = ec.withColumn("knowledge_id", F.col("e_knowledge_id"))

# -----------------------
# Step 4: Project knowledge table to authoritative metadata
# -----------------------
k = (
    knowledge_df.select(
        F.col("knowledge_id").alias("k_knowledge_id"),
        F.col("business_domain").alias("business_domain"),
        F.col("event_date").alias("event_date"),
        F.col("equipment_id").alias("equipment_id"),
        F.col("line_id").alias("line_id"),
        F.col("source_reference").alias("source_reference")
    )
)

# -----------------------
# Step 5: Join to knowledge (inner only)
# -----------------------
full = ec.join(k, on=F.col("knowledge_id") == F.col("k_knowledge_id"), how="inner")


index_input_df = full.select(
    # Identity
    F.col("e_chunk_id").alias("chunk_id"),
    F.col("knowledge_id").alias("knowledge_id"),

    # Vector fields
    F.col("embedding_vector"),
    F.col("embedding_dim"),
    F.col("embedding_model_name"),
    F.col("embedding_model_version"),

    # Filterable metadata
    F.col("c_knowledge_type").alias("knowledge_type"),
    F.col("business_domain"),
    F.col("event_date"),
    F.col("equipment_id"),
    F.col("line_id"),
    F.col("source_reference"),

    # Internal audit fields
    F.col("chunk_index"),
    F.col("chunk_token_count"),
    F.col("chunk_text"),
    F.col("chunk_text_hash"),
    F.col("embedded_at"),
    F.col("embedding_run_id"),
    F.col("chunk_pipeline_run_id"),
    F.col("created_at"),
    F.col("knowledge_id_mismatch")
)


index_input_df = index_input_df.dropDuplicates(["chunk_id", "embedding_model_version"])


index_input_df.createOrReplaceTempView(INDEX_INPUT_VIEW + "_temp")


index_input_df.createOrReplaceTempView(INDEX_INPUT_VIEW)


print(f"Created index-input view: {INDEX_INPUT_VIEW}")
print("Next: Stage 5B validation should hard-fail if knowledge_id_mismatch = true for any row.")
