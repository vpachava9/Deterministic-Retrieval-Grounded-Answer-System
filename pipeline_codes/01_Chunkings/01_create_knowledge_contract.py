from pyspark.sql.types import (
    StructType, StructField, StringType, DateType, MapType
)

knowledge_schema = StructType([
    StructField("knowledge_id", StringType(), False),
    StructField("knowledge_type", StringType(), False),
    StructField("business_domain", StringType(), False),
    StructField("content_text", StringType(), False),
    StructField("source_reference", StringType(), False),
    StructField("event_date", DateType(), True),
    StructField("metadata", MapType(StringType(), StringType()), True)
])

empty_df = spark.createDataFrame([], knowledge_schema)

empty_df.write.format("delta") \
    .mode("overwrite") \
    .save(
        "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_assets"
    )