chunks_df = spark.read.format("delta").load(chunks_path_v1)

from pyspark.sql.functions import col, count, when, length, trim

chunks_df.select(
    count(when(col("knowledge_chunk_id").isNull(), 1)).alias("null_chunk_id"),
    count(when(col("knowledge_id").isNull(), 1)).alias("null_knowledge_id")
).show()

bad_text = chunks_df.filter(
    col("chunk_text").isNull() |
    (length(trim(col("chunk_text"))) < 40)
)

print("bad_text_count =", bad_text.count())