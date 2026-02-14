from pyspark.sql.types import (
    StructType, StructField,
    StringType, IntegerType, DateType, TimestampType
)

chunk_schema = StructType([
    StructField("knowledge_chunk_id", StringType(), False),
    StructField("knowledge_id", StringType(), False),
    StructField("knowledge_type_original", StringType(), True),
    StructField("knowledge_type_effective", StringType(), True),
    StructField("chunk_index", IntegerType(), True),
    StructField("chunk_text", StringType(), True),
    StructField("chunk_token_count", IntegerType(), True),
    StructField("business_domain", StringType(), True),
    StructField("equipment_id", StringType(), True),
    StructField("line_id", StringType(), True),
    StructField("event_date", DateType(), True),
    StructField("source_reference", StringType(), True),
    StructField("created_at", TimestampType(), True),
])

empty_chunks_df = spark.createDataFrame([], chunk_schema)

empty_chunks_df.write.format("delta") \
    .mode("overwrite") \
    .save(
        "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_chunks/"
    )