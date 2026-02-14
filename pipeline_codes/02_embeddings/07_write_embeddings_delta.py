from pyspark.sql.functions import lit, current_timestamp

embedding_results_df = spark.createDataFrame(embedding_results_schema)

embedding_results_df = embedding_results_df \
    .withColumn("embedding_created_at", current_timestamp()) \
    .withColumn("pipeline_run_id", lit(run_id)) \
    .withColumn("source_chunk_version", lit("semantic_v2"))

embedding_results_df.write.format("delta").mode("append").save(embeddings_path)