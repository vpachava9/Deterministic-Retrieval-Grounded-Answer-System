knowledge_df = (
    spark.read
         .format("delta")
         .load(
             "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_assets/"
         )
)

knowledge_df.printSchema()

from pyspark.sql.functions import col, when, lower, trim

knowledge_with_type = (
    knowledge_df
    .withColumn(
        "knowledge_type_effective",
        when(col("knowledge_type").isNull(), "QUALITY")
        .otherwise(lower(trim(col("knowledge_type"))))
    )
)

from pyspark.sql.functions import col, lower, trim, length

placeholder_condition = (
    col("content_text").isNull()
    | (trim(col("content_text")) == "")
    | lower(trim(col("content_text"))).rlike(
        "n/a|na|none|tbd|all good|no issues|ok|passed"
    )
)

action_signal = lower(col("content_text")).rlike(
    "shutdown|failure|alarm|trip|leak|replaced|calibrated|lubricated|repaired|inspection failed|defect|exceeded|warning|must|do not|before|after|stopped"
)

numeric_signal = lower(col("content_text")).rlike(
    "\\d+(\\.\\d+)?\\s*(%|ppm|usd|hours|hrs|minutes|min|°c|bar|rpm)"
)

outcome_signal = lower(col("content_text")).rlike(
    "initiated|completed|failed|triggered|stopped|started|replaced"
)

short_low_signal = (
    (length(col("content_text")) < 120)
    & (~action_signal)
    & (~numeric_signal)
    & (~outcome_signal)
    & (~col("knowledge_type_effective").isin("sop", "maintenance"))
)

from pyspark.sql.functions import when

validated_knowledge = (
    knowledge_with_type
    .withColumn(
        "validation_status",
        when(placeholder_condition, "REJECTED")
        .when(short_low_signal, "REJECTED")
        .otherwise("APPROVED")
    )
)

approved_knowledge = validated_knowledge.filter(
    col("validation_status") == "APPROVED"
)

from pyspark.sql.functions import lit

incident_prod_chunks = (
    approved_knowledge
        .filter(col("knowledge_type_effective").isin("incident", "production"))
        .withColumn("chunk_index", lit(0))
        .withColumnRenamed("content_text", "chunk_text")
        .select(
            "knowledge_id",
            col("knowledge_type").alias("knowledge_type_original"),
            "knowledge_type_effective",
            "chunk_index",
            "chunk_text",
            "business_domain",
            "equipment_id",
            "line_id",
            "event_date",
            "source_reference"
        )
)

incident_prod_chunks.write \
    .format("delta") \
    .mode("append") \
    .save(
        "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_chunks/"
    )

from pyspark.sql.functions import col

sop_maint_raw = knowledge_with_type.filter(
    col("knowledge_type_effective").isin("sop", "maintenance")
)

sop_maint_raw.groupBy("knowledge_type_effective").count().show()

from pyspark.sql.functions import (
    split, explode, posexplode, trim, lit, current_timestamp
)

SECTION_REGEX = r"(?:\n\s*(?:SCOPE|SAFETY|PRE-STARTUP|STARTUP|OPERATION|INSPECTION|MAINTENANCE|CALIBRATION|WARNING|NOTE|Step\s+\d+)\s*:?)"

sections_df = (
    sop_maint_raw
    .withColumn("sections", split(col("content_text"), SECTION_REGEX))
    .select(
        "knowledge_id",
        "knowledge_type",
        "knowledge_type_effective",
        "business_domain",
        "equipment_id",
        "line_id",
        "event_date",
        "source_reference",
        posexplode("sections").alias("chunk_index", "chunk_text")
    )
    .withColumn("chunk_text", trim(col("chunk_text")))
    .filter(col("chunk_text") != "")
)

sop_maint_chunks = (
    sections_df
    .withColumn(
        "chunk_token_count",
        (length(regexp_replace(col("chunk_text"), r"\s+", " ")) / 4).cast("int")
    )
    .withColumn("knowledge_chunk_id", expr("uuid()"))
    .withColumn("created_at", current_timestamp())
)

import re

def split_sop_sections(text):
    if text is None:
        return []

    sections = re.split(
        r'(?=(SCOPE:|SAFETY|PRE-|STARTUP|OPERATION|PROCEDURE|EMERGENCY|MAINTENANCE|REVISION))',
        text,
        flags=re.IGNORECASE
    )

    merged = []
    buffer = ""

    for part in sections:
        if len(buffer) + len(part) < 2500:
            buffer += " " + part
        else:
            merged.append(buffer.strip())
            buffer = part

    if buffer.strip():
        merged.append(buffer.strip())

    return merged

from pyspark.sql.functions import explode, udf
from pyspark.sql.types import ArrayType, StringType

split_udf = udf(split_sop_sections, ArrayType(StringType()))

sop_sections_df = (
    sop_df
    .withColumn("sections", split_udf(col("content_text")))
    .withColumn("chunk_text", explode(col("sections")))
    .drop("sections")
)

sop_sections_df = sop_sections_df.withColumn(
    "chunk_token_count",
    (length(regexp_replace(col("chunk_text"), r"\s+", " ")) / 4).cast("int")
)

sop_split_df = (
    sop_chunks_df
    .withColumn("chunk_text", explode(split_udf(col("chunk_text"))))
)

sop_split_df = sop_split_df.withColumn(
    "chunk_token_count",
    (length(regexp_replace(col("chunk_text"), r"\s+", " ")) / 4).cast("int")
)

from pyspark.sql.functions import lit

def normalize_chunks(df):
    return (
        df
        .withColumn("knowledge_type_original", col("knowledge_type"))
        .select(
            "knowledge_chunk_id",
            "knowledge_id",
            "knowledge_type_original",
            "knowledge_type_effective",
            "chunk_index",
            "chunk_text",
            "chunk_token_count",
            "business_domain",
            "equipment_id",
            "line_id",
            "event_date",
            "source_reference",
            "created_at"
        )
    )

from pyspark.sql.functions import expr, current_timestamp

incident_prod_chunks = (
    incident_prod_chunks
    .withColumn("knowledge_chunk_id", expr("uuid()"))
    .withColumn("created_at", current_timestamp())
)

from pyspark.sql.functions import length, regexp_replace, col

incident_prod_chunks = (
    incident_prod_chunks
    .withColumn(
        "chunk_token_count",
        (length(regexp_replace(col("chunk_text"), r"\s+", " ")) / 4).cast("int")
    )
)

incident_prod_chunks_norm = (
    incident_prod_chunks
    .select(
        "knowledge_chunk_id",
        "knowledge_id",
        "knowledge_type_original",
        "knowledge_type_effective",
        "chunk_index",
        "chunk_text",
        "chunk_token_count",
        "business_domain",
        "equipment_id",
        "line_id",
        "event_date",
        "source_reference",
        "created_at"
    )
)

from pyspark.sql.functions import col, length, regexp_replace, expr, current_timestamp

maintenance_chunks_norm = (
    sop_maint_chunks
    .filter(col("knowledge_type_effective") == "maintenance")
    .withColumn("knowledge_type_original", col("knowledge_type"))
    .withColumn(
        "chunk_token_count",
        (length(regexp_replace(col("chunk_text"), r"\s+", " ")) / 4).cast("int")
    )
    .withColumn("knowledge_chunk_id", expr("uuid()"))
    .withColumn("created_at", current_timestamp())
    .select(
        "knowledge_chunk_id",
        "knowledge_id",
        "knowledge_type_original",
        "knowledge_type_effective",
        "chunk_index",
        "chunk_text",
        "chunk_token_count",
        "business_domain",
        "equipment_id",
        "line_id",
        "event_date",
        "source_reference",
        "created_at"
    )
)

from pyspark.sql.functions import expr, current_timestamp

sop_split_chunks_norm = (
    sop_split_df
    .withColumn("knowledge_type_original", col("knowledge_type"))
    .withColumn("knowledge_chunk_id", expr("uuid()"))
    .withColumn("created_at", current_timestamp())
    .select(
        "knowledge_chunk_id",
        "knowledge_id",
        "knowledge_type_original",
        "knowledge_type_effective",
        "chunk_index",
        "chunk_text",
        "chunk_token_count",
        "business_domain",
        "equipment_id",
        "line_id",
        "event_date",
        "source_reference",
        "created_at"
    )
)

all_chunks = (
    incident_prod_chunks_norm
    .unionByName(maintenance_chunks_norm)
    .unionByName(sop_split_chunks_norm)
)

all_chunks.filter(
    col("chunk_text").isNull() | (length(col("chunk_text")) < 40)
).count()

all_chunks.filter(col("knowledge_chunk_id").isNull()).count()

all_chunks.count() == all_chunks.select("knowledge_chunk_id").distinct().count()