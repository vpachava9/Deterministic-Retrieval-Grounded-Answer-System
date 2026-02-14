from datetime import datetime, timezone
from pyspark.sql.types import *
from pyspark.sql import functions as F

storage_path = "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/rag/public_responses/v1/"

public_response_schema = StructType([
    StructField("request_id", StringType(), False),
    StructField("run_id", StringType(), False),
    StructField("timestamp_utc", TimestampType(), False),
    StructField("status", StringType(), False),
    StructField("answer", StringType(), True),

    StructField("citations", ArrayType(
        StructType([
            StructField("anchor", StringType(), False),
            StructField("knowledge_id", StringType(), True),
            StructField("source_reference", StringType(), True),
            StructField("event_date", StringType(), True),
            StructField("equipment_id", StringType(), True),
        ])
    ), True),

    StructField("prompt_tokens", IntegerType(), True),
    StructField("completion_tokens", IntegerType(), True),
    StructField("total_tokens", IntegerType(), True),
    StructField("latency_ms", IntegerType(), True),

    StructField("model_name", StringType(), True),
    StructField("embedding_model", StringType(), True),
    StructField("index_version", StringType(), True),
    StructField("policy_version", StringType(), True),
])


def persist_public_response(
    public_response,
    r5_result,
    llm_result,
    answer_bundle,
    run_id: str
):

    trace = getattr(answer_bundle, "trace", {}) or {}

    token_usage = getattr(public_response, "token_usage", {}) or {}

    row_data = [{
        "request_id": public_response.request_id,
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc),
        "status": public_response.status,
        "answer": public_response.answer if public_response.status == "OK" else None,
        "citations": public_response.citations or [],
        "prompt_tokens": token_usage.get("prompt_tokens"),
        "completion_tokens": token_usage.get("completion_tokens"),
        "total_tokens": token_usage.get("total_tokens"),
        "latency_ms": public_response.latency_ms,
        "model_name": getattr(llm_result, "model_name", "unknown"),
        "embedding_model": trace.get("embedding_model"),
        "index_version": trace.get("index_version"),
        "policy_version": trace.get("policy_version"),
    }]

    df = spark.createDataFrame(row_data, schema=public_response_schema)
    df.write.format("delta").mode("append").save(storage_path)