maintenance_df = spark.read.option("header", True).csv(
    "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/maintenance/gold_equipment_maintenance.csv"
)

maintenance_df.printSchema()
maintenance_df.show(20, truncate=False)
maintenance_df.count()

from pyspark.sql.functions import col, lit, concat_ws, to_date, create_map

maintenance_knowledge_df = maintenance_df.withColumn(
    "content_text",
    concat_ws(
        " ",
        lit("On"), col("maintenance_date"), lit(","),
        lit("a"), col("maintenance_type"), lit("maintenance was performed on"),
        col("equipment_name"), lit("("), col("equipment_id"), lit(")"),
        lit("on production line"), col("line_id") + lit("."),
        lit("The maintenance addressed"), col("maintenance_category"),
        lit("issues related to"), col("failure_mode") + lit("."),
        lit("Maintenance activities included"), col("work_performed") + lit("."),
        lit("The equipment status after maintenance was"), col("equipment_status") + lit(".")
    )
).withColumn(
    "event_date",
    to_date(col("maintenance_date"))
).withColumn(
    "knowledge_id",
    col("maintenance_id")
).withColumn(
    "knowledge_type",
    lit("maintenance")
).withColumn(
    "business_domain",
    lit("manufacturing_operations")
).withColumn(
    "source_reference",
    lit("gold_equipment_maintenance.csv")
).withColumn(
    "metadata",
    create_map(
        lit("maintenance_type"), col("maintenance_type"),
        lit("maintenance_category"), col("maintenance_category"),
        lit("technician_name"), col("technician_name"),
        lit("certification_level"), col("certification_level"),
        lit("duration_hours"), col("duration_hours"),
        lit("total_cost_usd"), col("total_cost_usd"),
        lit("downtime_impact"), col("downtime_impact"),
        lit("work_priority"), col("work_priority"),
        lit("equipment_status"), col("equipment_status")
    )
)

final_maintenance_knowledge_df = maintenance_knowledge_df.select(
    "knowledge_id",
    "knowledge_type",
    "business_domain",
    "content_text",
    "source_reference",
    "event_date",
    "metadata"
)

final_maintenance_knowledge_df.write \
  .format("delta") \
  .mode("append") \
  .save("abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_assets")