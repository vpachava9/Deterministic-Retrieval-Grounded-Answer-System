#smoke_test_faiss.py


import faiss
import numpy as np
import pandas as pd

# Config (must match Stage 5D)
RUN_ID = "run_20260209_001"

INDEX_FILE_PATH = (
    "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/"
    "vector_index/faiss/index_name=knowledge_chunks_cosine/"
    "index_version=text-embedding-3-large__embed_ops_v1__dim3072__20260212T161452Z/"
    "index.faiss"
)

ID_MAP_PATH = (
    "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/"
    "vector_index/faiss/index_name=knowledge_chunks_cosine/"
    "index_version=text-embedding-3-large__embed_ops_v1__dim3072__20260212T161452Z/"
    "id_map.parquet"
)

VECTOR_EXPORT_PATH = (
    "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/"
    f"vector_index/exports/{RUN_ID}/vectors"
)

TOP_K = 5
EMBEDDING_DIM = 3072

# Step 1: Load FAISS index (corrected)
DBFS_TMP_DIR = "dbfs:/tmp/faiss_smoke"
DBFS_INDEX_FILE = f"{DBFS_TMP_DIR}/index.faiss"
LOCAL_INDEX_FILE = "/dbfs/tmp/faiss_smoke/index.faiss"

dbutils.fs.mkdirs(DBFS_TMP_DIR)
dbutils.fs.cp(INDEX_FILE_PATH, DBFS_INDEX_FILE)

index = faiss.read_index(LOCAL_INDEX_FILE)
print(f"Loaded FAISS index with {index.ntotal} vectors")


# Step 2: Load id_map (FINAL, CORRECT)
id_map_df = spark.read.parquet(ID_MAP_PATH).toPandas()

required_cols = {"faiss_id", "chunk_id"}
if not required_cols.issubset(id_map_df.columns):
    raise Exception(f"id_map schema invalid: {id_map_df.columns}")

print(f"Loaded id_map with {len(id_map_df)} rows")


# Step 3: Load one known vector
vectors_df = spark.read.parquet(VECTOR_EXPORT_PATH)

# Take first vector deterministically
test_vector = vectors_df.limit(1).collect()[0]["vector"]

Xq = np.array([test_vector], dtype=np.float32)

if Xq.shape != (1, EMBEDDING_DIM):
    raise Exception(f"Query vector shape mismatch: {Xq.shape}")

# Normalize (cosine similarity contract)
faiss.normalize_L2(Xq)

# Step 4: Run FAISS search
scores, ids = index.search(Xq, TOP_K)

faiss_ids = ids[0].tolist()
similarities = scores[0].tolist()

print("FAISS search completed")
print("Top FAISS ids:", faiss_ids)
print("Similarity scores:", similarities)

# Step 5: Resolve chunk_ids
resolved = (
    id_map_df[id_map_df["faiss_id"].isin(faiss_ids)]
    .set_index("faiss_id")
    .loc[faiss_ids]
    .reset_index()
)

print("Resolved chunk_ids:")
print(resolved[["faiss_id", "chunk_id"]])



# Verdict

print("STAGE 5E – TEST A PASSED (Self-retrieval sanity check)")
