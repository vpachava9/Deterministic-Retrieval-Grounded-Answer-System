from pyspark.sql.functions import row_number
from pyspark.sql.window import Window

window_spec = Window.orderBy("knowledge_chunk_id")

embedding_candidates = semantic_v2.withColumn(
    "row_num",
    row_number().over(window_spec)
).withColumn(
    "batch_id",
    ((col("row_num") - 1) / 50).cast("int")
)