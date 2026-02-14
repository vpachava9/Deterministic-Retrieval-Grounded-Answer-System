#build_faiss_index.py


import json
import os
import numpy as np
import pandas as pd
from datetime import datetime, timezone

import faiss
from pyspark.sql import functions as F

# Inputs
RUN_ID = "run_20260209_001"
EXPORT_BASE_PATH = "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/vector_index/exports"

VECTOR_EXPORT_PATH = f"{EXPORT_BASE_PATH}/{RUN_ID}/vectors"
METADATA_EXPORT_PATH = f"{EXPORT_BASE_PATH}/{RUN_ID}/metadata"

# Index config
INDEX_NAME = "knowledge_chunks_cosine"
EMBEDDING_MODEL_NAME = "text-embedding-3-large"
EMBEDDING_MODEL_VERSION = "embed_ops_v1"
EMBEDDING_DIM = 3072
SIMILARITY = "cosine"

INDEX_VERSION = (
    f"{EMBEDDING_MODEL_NAME}__"
    f"{EMBEDDING_MODEL_VERSION}__"
    f"dim{EMBEDDING_DIM}__"
    f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
)

# Output paths
INDEX_BASE_PATH = "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/vector_index/faiss"
INDEX_VERSION_PATH = f"{INDEX_BASE_PATH}/index_name={INDEX_NAME}/index_version={INDEX_VERSION}"

INDEX_FILE_PATH = f"{INDEX_VERSION_PATH}/index.faiss"
ID_MAP_PATH = f"{INDEX_VERSION_PATH}/id_map.parquet"
MANIFEST_PATH = f"{INDEX_VERSION_PATH}/manifest.json"
METADATA_INDEX_PATH = f"{INDEX_VERSION_PATH}/metadata.parquet"


# Local filesystem paths
LOCAL_TMP_DIR = f"/dbfs/tmp/faiss_build/{INDEX_VERSION}"
LOCAL_INDEX_FILE = f"{LOCAL_TMP_DIR}/index.faiss"
LOCAL_MANIFEST_FILE = f"{LOCAL_TMP_DIR}/manifest.json"

DBFS_INDEX_FILE = f"dbfs:/tmp/faiss_build/{INDEX_VERSION}/index.faiss"
DBFS_MANIFEST_FILE = f"dbfs:/tmp/faiss_build/{INDEX_VERSION}/manifest.json"

# Step 1: Load exports (ordering already guaranteed)
vectors_df = spark.read.parquet(VECTOR_EXPORT_PATH)
metadata_df = spark.read.parquet(METADATA_EXPORT_PATH)

vector_count = vectors_df.count()
meta_count = metadata_df.count()

if vector_count != meta_count:
    raise Exception(f"Count mismatch: vectors={vector_count}, metadata={meta_count}")

# Collect vectors
X = np.array(
    [r["vector"] for r in vectors_df.select("vector").collect()],
    dtype=np.float32
)

if X.ndim != 2 or X.shape[1] != EMBEDDING_DIM:
    raise Exception(f"Invalid vector shape {X.shape}")

# Collect chunk_ids in the same order
chunk_ids = [r["chunk_id"] for r in metadata_df.select("chunk_id").collect()]

# Step 2: Normalize for cosine similarity
faiss.normalize_L2(X)
# Step 3: Build FAISS index
index = faiss.IndexFlatIP(EMBEDDING_DIM)
index.add(X)

if index.ntotal != X.shape[0]:
    raise Exception("FAISS index count mismatch")

# Step 4: Persist FAISS index
os.makedirs(LOCAL_TMP_DIR, exist_ok=True)
faiss.write_index(index, LOCAL_INDEX_FILE)

dbutils.fs.mkdirs(f"dbfs:/tmp/faiss_build/{INDEX_VERSION}")
dbutils.fs.cp(DBFS_INDEX_FILE, INDEX_FILE_PATH)

# Step 5: Write id_map
id_map_pdf = pd.DataFrame({
    "faiss_id": np.arange(X.shape[0], dtype=np.int64),
    "chunk_id": chunk_ids
})

spark.createDataFrame(id_map_pdf).write.mode("overwrite").parquet(ID_MAP_PATH)
metadata_df.write.mode("overwrite").parquet(METADATA_INDEX_PATH)

# Step 6: Write manifest

manifest = {
    "index_name": INDEX_NAME,
    "index_version": INDEX_VERSION,
    "embedding_model_name": EMBEDDING_MODEL_NAME,
    "embedding_model_version": EMBEDDING_MODEL_VERSION,
    "embedding_dim": EMBEDDING_DIM,
    "similarity": SIMILARITY,
    "vector_count": int(X.shape[0]),
    "export_run_id": RUN_ID,
    "built_at_utc": datetime.now(timezone.utc).isoformat(),
    "index_file": INDEX_FILE_PATH,
    "id_map": ID_MAP_PATH,
    "metadata": METADATA_INDEX_PATH
}

with open(LOCAL_MANIFEST_FILE, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

dbutils.fs.cp(DBFS_MANIFEST_FILE, MANIFEST_PATH)

print("FAISS INDEX BUILD COMPLETED")
print(f"Index version: {INDEX_VERSION}")
print(f"Index path:    {INDEX_FILE_PATH}")
print(f"Next stage: Stage 5E – Retrieval smoke test")
