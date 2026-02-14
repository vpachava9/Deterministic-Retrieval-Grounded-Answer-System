#export_vectors_for_faiss.py


from pyspark.sql import functions as F

INDEX_INPUT_VIEW = "vw_vector_index_input_v1"

EXPORT_BASE_PATH = "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/vector_index/exports"
RUN_ID = "run_20260209_001"  # in production this is passed from orchestration

VECTOR_EXPORT_PATH = f"{EXPORT_BASE_PATH}/{RUN_ID}/vectors"
ID_MAP_EXPORT_PATH = f"{EXPORT_BASE_PATH}/{RUN_ID}/id_map"
METADATA_EXPORT_PATH = f"{EXPORT_BASE_PATH}/{RUN_ID}/metadata"

# Load validated index input
df = spark.table(INDEX_INPUT_VIEW)

# Enforce deterministic ordering
df_ordered = df.orderBy(F.col("chunk_id").asc())

# Export vectors
vectors_df = df_ordered.select(
    F.col("embedding_vector").alias("vector")
)

vectors_df.write \
    .mode("overwrite") \
    .format("parquet") \
    .save(VECTOR_EXPORT_PATH)

# Export ID map
id_map_df = df_ordered.select(
    F.monotonically_increasing_id().alias("faiss_id"),
    F.col("chunk_id")
)

id_map_df.write \
    .mode("overwrite") \
    .format("parquet") \
    .save(ID_MAP_EXPORT_PATH)

# Export minimal metadata snapshot
metadata_df = df_ordered.select(
    F.col("chunk_id"),
    F.col("chunk_text"), 
    F.col("knowledge_id"),
    F.col("knowledge_type"),
    F.col("event_date"),
    F.col("equipment_id"),
    F.col("line_id"),
    F.col("source_reference")
)

metadata_df.write \
    .mode("overwrite") \
    .format("parquet") \
    .save(METADATA_EXPORT_PATH)


# Summary

print("FAISS EXPORT COMPLETED")
print(f"Vectors path:   {VECTOR_EXPORT_PATH}")
print(f"ID map path:    {ID_MAP_EXPORT_PATH}")
print(f"Metadata path:  {METADATA_EXPORT_PATH}")
print("Next stage: Stage 5D – Build FAISS index (Python)")
