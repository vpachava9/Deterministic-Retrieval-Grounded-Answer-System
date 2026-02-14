# validate_index_input.py


from pyspark.sql import functions as F

INDEX_INPUT_VIEW = "vw_vector_index_input_v1"
EXPECTED_DIM = 3072

df = spark.table(INDEX_INPUT_VIEW)


# Base counts

total_rows = df.count()


# Null checks (hard fail)

required_columns = [
    "chunk_id",
    "knowledge_id",
    "embedding_vector",
    "embedding_dim",
    "embedding_model_name",
    "embedding_model_version",
    "knowledge_type"
]

null_counts = {
    col: df.filter(F.col(col).isNull()).count()
    for col in required_columns
}


# Duplicate key check (hard fail)

duplicate_count = (
    df.groupBy("chunk_id", "embedding_model_version")
      .count()
      .filter(F.col("count") > 1)
      .count()
)


# Dimension mismatch (hard fail)

dim_mismatch_count = (
    df.filter(F.col("embedding_dim") != F.lit(EXPECTED_DIM)).count()
)


# Vector length mismatch (hard fail)

vector_length_mismatch_count = (
    df.filter(F.size(F.col("embedding_vector")) != F.col("embedding_dim")).count()
)


# Knowledge ID mismatch (hard fail)

knowledge_id_mismatch_count = (
    df.filter(F.col("knowledge_id_mismatch") == F.lit(True)).count()
)


# Validation summary

validation_errors = []

if total_rows == 0:
    validation_errors.append("NO_ROWS_IN_INDEX_INPUT")

for col, cnt in null_counts.items():
    if cnt > 0:
        validation_errors.append(f"NULLS_IN_{col.upper()}")

if duplicate_count > 0:
    validation_errors.append("DUPLICATE_CHUNK_ID_MODEL_VERSION")

if dim_mismatch_count > 0:
    validation_errors.append("EMBEDDING_DIMENSION_MISMATCH")

if vector_length_mismatch_count > 0:
    validation_errors.append("VECTOR_LENGTH_MISMATCH")

if knowledge_id_mismatch_count > 0:
    validation_errors.append("KNOWLEDGE_ID_MISMATCH")


# Emit validation result

print("========== INDEX INPUT VALIDATION ==========")
print(f"Total rows: {total_rows}")
print(f"Duplicate keys: {duplicate_count}")
print(f"Dimension mismatch: {dim_mismatch_count}")
print(f"Vector length mismatch: {vector_length_mismatch_count}")
print(f"Knowledge ID mismatch: {knowledge_id_mismatch_count}")

for col, cnt in null_counts.items():
    print(f"Nulls in {col}: {cnt}")

print("===========================================")


# Hard fail if needed

if validation_errors:
    raise Exception(
        "INDEX INPUT VALIDATION FAILED: " + ", ".join(validation_errors)
    )

print("INDEX INPUT VALIDATION PASSED")
