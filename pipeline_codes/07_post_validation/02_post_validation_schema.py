from datetime import datetime, timezone
from pyspark.sql import Row
from pyspark.sql.types import *
from pyspark.sql import functions as F

storage_path = "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/rag/validations/v1/"

validation_schema = StructType([
    StructField("request_id", StringType(), False),
    StructField("run_id", StringType(), False),
    StructField("timestamp_utc", TimestampType(), False),
    StructField("generation_status", StringType(), False),
    StructField("validation_status", StringType(), False),
    StructField("failure_reason", StringType(), True),
    StructField("citation_count", IntegerType(), False),
    StructField("uncited_sentence_count", IntegerType(), False),
    StructField("invalid_anchor_count", IntegerType(), False),
    StructField("suspicious_new_ids", ArrayType(StringType()), True),
    StructField("refusal_detected", BooleanType(), False),
    StructField("length_ratio_flag", BooleanType(), False),
    StructField("validated_citations", ArrayType(StringType()), True),
    StructField("validated_answer_text", StringType(), True),
    StructField("model_name", StringType(), False),
    StructField("embedding_model", StringType(), True),
    StructField("index_version", StringType(), True),
    StructField("policy_version", StringType(), True),
])


def persist_r5_validation(
    r5_result,
    llm_result,
    answer_bundle,
    run_id: str
):

    trace = getattr(answer_bundle, "trace", {}) or {}

    row_data = [{
        "request_id": r5_result.request_id,
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc),
        "generation_status": r5_result.generation_status,
        "validation_status": r5_result.validation_status,
        "failure_reason": r5_result.failure_reason,
        "citation_count": int(r5_result.grounding_metrics.get("citation_count", 0)),
        "uncited_sentence_count": int(r5_result.grounding_metrics.get("uncited_sentence_count", 0)),
        "invalid_anchor_count": int(r5_result.grounding_metrics.get("invalid_anchor_count", 0)),
        "suspicious_new_ids": r5_result.grounding_metrics.get("suspicious_new_ids", []),
        "refusal_detected": bool(r5_result.grounding_metrics.get("refusal_detected", False)),
        "length_ratio_flag": bool(r5_result.grounding_metrics.get("length_ratio_flag", False)),
        "validated_citations": r5_result.validated_citations or [],
        "validated_answer_text": r5_result.validated_answer_text if r5_result.validation_status == "PASSED" else None,
        "model_name": getattr(llm_result, "model_name", "unknown"),
        "embedding_model": trace.get("embedding_model"),
        "index_version": trace.get("index_version"),
        "policy_version": trace.get("policy_version"),
    }]

    df = spark.createDataFrame(row_data, schema=validation_schema)

    df.write.format("delta").mode("append").save(storage_path)
