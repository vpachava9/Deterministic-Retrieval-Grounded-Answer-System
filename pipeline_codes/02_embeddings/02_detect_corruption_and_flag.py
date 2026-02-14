from pyspark.sql.functions import col, lit, current_timestamp, when, regexp_extract

has_bad_on_number = regexp_extract(col("chunk_text"), r"^On\s+(\d+(\.\d+)?)\s*,", 1) != ""
missing_event_date = col("event_date").isNull()

corrupted_chunks = chunks_df.withColumn(
    "corruption_reason",
    when(missing_event_date & has_bad_on_number, lit("MALFORMED_EVENT_DATE_IN_TEXT"))
    .when(missing_event_date & col("knowledge_type_effective").isin("incident","maintenance","production"), lit("MISSING_EVENT_DATE"))
    .otherwise(lit("UNKNOWN_CORRUPTION"))
).filter(col("corruption_reason") != "UNKNOWN_CORRUPTION")