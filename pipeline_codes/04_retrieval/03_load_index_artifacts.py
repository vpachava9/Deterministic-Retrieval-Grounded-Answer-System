# load_index_artifacts.py

import os
import json
import faiss

from databricks.sdk.runtime import spark, dbutils
from pyspark.sql.functions import col


class IndexNotFoundError(Exception):
    pass


def load_index_artifacts(index_name: str, index_version: str, config: dict):
    """
    Load FAISS index artifacts for retrieval.

    Expected storage layout (LOCKED CONTRACT):

    vector_index/faiss/
      index_name=<index_name>/
        index_version=<index_version>/
          index.faiss
          manifest.json
          id_map.parquet/   (Parquet directory)
    """

    # -------------------------------
    # 1. Build ABFS index path
    # -------------------------------
    base_path = config["paths"]["faiss_index_root"]

    abfs_index_path = (
        f"{base_path}/"
        f"index_name={index_name}/"
        f"index_version={index_version}"
    )

    # -------------------------------
    # 2. Validate index directory exists
    # -------------------------------
    try:
        files = dbutils.fs.ls(abfs_index_path)
    except Exception:
        raise IndexNotFoundError(
            f"FAISS index directory not found: {abfs_index_path}"
        )

    file_names = {os.path.basename(f.path.rstrip("/")) for f in files}

    if "index.faiss" not in file_names:
        raise IndexNotFoundError("Missing index.faiss")

    if "manifest.json" not in file_names:
        raise IndexNotFoundError("Missing manifest.json")

    if "id_map.parquet" not in file_names:
        raise IndexNotFoundError("Missing id_map.parquet directory")

    if "metadata.parquet" not in file_names:
        raise IndexNotFoundError("Missing metadata.parquet directory")
    # -------------------------------
    # 3. Prepare local cache
    # -------------------------------
    local_root = config["paths"]["local_index_cache"]
    local_index_path = os.path.join(local_root, index_name, index_version)
    os.makedirs(local_index_path, exist_ok=True)

    # -------------------------------
    # 4. Copy flat files locally
    # -------------------------------
    dbutils.fs.cp(
        f"{abfs_index_path}/index.faiss",
        f"file:{os.path.join(local_index_path, 'index.faiss')}",
        recurse=False
    )

    dbutils.fs.cp(
        f"{abfs_index_path}/manifest.json",
        f"file:{os.path.join(local_index_path, 'manifest.json')}",
        recurse=False
    )

    # -------------------------------
    # 5. Load FAISS index
    # -------------------------------
    faiss_index = faiss.read_index(
        os.path.join(local_index_path, "index.faiss")
    )

    # -------------------------------
    # 6. Load id_map (STRING canonical)
    # -------------------------------
    id_map_df = (
        spark.read.format("parquet")
        .load(f"{abfs_index_path}/id_map.parquet")
        .select("faiss_id", "chunk_id")
    )

    metadata_df = (
        spark.read.format("parquet")
        .load(f"{abfs_index_path}/metadata.parquet")
    )

    nulls = id_map_df.filter(
        "faiss_id IS NULL OR chunk_id IS NULL"
    ).count()

    if nulls > 0:
        raise IndexNotFoundError(
            f"id_map.parquet contains {nulls} rows with NULL ids"
        )

    id_map = {
        int(row["faiss_id"]): row["chunk_id"]  # chunk_id stays STRING (UUID)
        for row in id_map_df.collect()
    }

    # -------------------------------
    # 7. Load manifest
    # -------------------------------
    with open(os.path.join(local_index_path, "manifest.json"), "r") as f:
        manifest = json.load(f)

    # -------------------------------
    # 8. Return artifacts
    # -------------------------------
    return {
        "faiss_index": faiss_index,
        "id_map": id_map,
        "manifest": manifest,
        "metadata_df": metadata_df,
        "abfs_path": abfs_index_path
    }
