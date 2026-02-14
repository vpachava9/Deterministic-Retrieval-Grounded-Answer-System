incidents_df = spark.read.option("header", True).csv(
    "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/incidents/gold_incidents.csv"
)

from pyspark.sql.functions import concat_ws, lit, col, to_date

incidents_enriched_df = incidents_df.withColumn(
    "content_text",
    concat_ws(
        " ",
        lit("On"),
        col("incident_date") + lit(","),
        lit("the equipment"),
        col("equipment_name"),
        lit("("),
        col("equipment_type"),
        lit(") on production line"),
        col("line_id"),
        lit("experienced a"),
        col("failure_type") + lit("."),
        lit("The failure was categorized as"),
        col("failure_category") + lit("."),
        lit("The root cause identified was"),
        col("root_cause") + lit("."),
        lit("This incident resulted in"),
        col("downtime_minutes"),
        lit("minutes of downtime and was resolved by"),
        col("resolution_action") + lit("."),
        lit("The severity level of this incident was"),
        col("severity") + lit(".")
    )
).withColumn(
    "event_date",
    to_date(col("incident_date"))
)

from pyspark.sql.functions import create_map

incidents_enriched_df = incidents_enriched_df.withColumn(
    "metadata",
    create_map(
        lit("shift"), col("shift"),
        lit("reported_by"), col("reported_by"),
        lit("verified_by"), col("verified_by"),
        lit("environmental_temp_c"), col("environmental_temp_c"),
        lit("humidity_percent"), col("humidity_percent"),
        lit("production_impact_units"), col("production_impact_units"),
        lit("labor_hours"), col("labor_hours"),
        lit("parts_cost_usd"), col("parts_cost_usd"),
        lit("mttr_minutes"), col("mttr_minutes"),
        lit("mtbf_hours"), col("mtbf_hours")
    )
)

from pyspark.sql.functions import expr, lit

final_incidents_knowledge_df = incidents_enriched_df.select(
    expr("uuid()").alias("knowledge_id"),
    lit("incident").alias("knowledge_type"),
    lit("operations").alias("business_domain"),
    col("content_text"),
    col("incident_id").alias("source_reference"),
    col("event_date"),
    col("metadata")
)

from pyspark.sql.functions import col

final_incidents_knowledge_df.filter(
    col("knowledge_id").isNull() |
    col("knowledge_type").isNull() |
    col("business_domain").isNull() |
    col("content_text").isNull()
).count()

from pyspark.sql.functions import size

final_incidents_knowledge_df.filter(
    col("metadata").isNull() | (size(col("metadata")) == 0)
).count()

final_incidents_knowledge_df.write.format("delta") \
    .mode("append") \
    .save("abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_assets")