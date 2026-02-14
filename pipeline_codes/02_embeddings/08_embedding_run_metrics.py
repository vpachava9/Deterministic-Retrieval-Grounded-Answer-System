from pyspark.sql.functions import lit, current_timestamp

metrics_df = spark.createDataFrame([{
    "pipeline_run_id": run_id,
    "total_chunks_scanned": total_scanned,
    "total_chunks_embedded": total_embedded,
    "total_chunks_failed": total_failed,
    "run_timestamp": current_timestamp()
}])

metrics_df.write.format("delta").mode("append").save(metrics_path)