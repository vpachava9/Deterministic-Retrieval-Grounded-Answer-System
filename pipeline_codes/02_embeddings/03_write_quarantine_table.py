from pyspark.sql.functions import current_timestamp, lit

quarantine_df = corrupted_chunks \
    .withColumn("detected_at", current_timestamp()) \
    .withColumn("source_table_version", lit("gold_knowledge_chunks_v1")) \
    .withColumn("pipeline_run_id", lit(run_id))

quarantine_df.write.format("delta").mode("append").save(quarantine_path)