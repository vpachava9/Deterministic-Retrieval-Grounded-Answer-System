quality_df = spark.read.option("header", True).csv(
    "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/quality/gold_quality_metrics.csv"
)

quality_df.printSchema()
quality_df.show(10, truncate=False)
quality_df.count()

from pyspark.sql.functions import (
    concat_ws, lit, col, trim, coalesce, to_date
)

quality_enriched_df = quality_df.withColumn(
    "content_text",
    concat_ws(
        " ",
        lit("On"),
        col("inspection_date"),
        lit(", a quality inspection of product"),
        trim(col("product_name")),
        lit("("),
        trim(col("product_sku")),
        lit(") on production line"),
        trim(col("line_id")),
        lit("detected a"),
        coalesce(trim(col("defect_type")), lit("quality defect")),
        lit("defect categorized as"),
        coalesce(trim(col("defect_category")), lit("unspecified category")),
        lit(". A total of"),
        coalesce(col("defect_count"), lit("an unknown number of")),
        lit("defects were found out of"),
        coalesce(col("total_inspected"), lit("an unspecified number of")),
        lit("units inspected"),
        lit("(defect rate"),
        coalesce(col("defect_rate_percent"), lit("unknown")),
        lit("%)."),
        lit("The inspection occurred during the"),
        coalesce(trim(col("inspection_stage")), lit("inspection")),
        lit("stage, and corrective action included"),
        coalesce(trim(col("corrective_action")), lit("standard quality procedures")),
        lit(".")
    )
).withColumn(
    "event_date",
    to_date(col("inspection_date"))
)

from pyspark.sql.functions import create_map, lit

quality_with_metadata_df = quality_enriched_df.withColumn(
    "metadata",
    create_map(
        lit("product_sku"), col("product_sku"),
        lit("batch_id"), col("batch_id"),
        lit("inspection_stage"), col("inspection_stage"),
        lit("defect_type"), col("defect_type"),
        lit("defect_category"), col("defect_category"),
        lit("defect_rate_percent"), col("defect_rate_percent"),
        lit("defect_rate_ppm"), col("defect_rate_ppm"),
        lit("specification_limit_percent"), col("specification_limit_percent"),
        lit("specification_type"), col("specification_type"),
        lit("inspector_name"), col("inspector_name"),
        lit("measurement_tool"), col("measurement_tool"),
        lit("cost_impact_usd"), col("cost_impact_usd"),
        lit("rework_hours"), col("rework_hours"),
        lit("scrap_count"), col("scrap_count"),
        lit("shift"), col("shift"),
        lit("temperature_c"), col("temperature_c"),
        lit("humidity_percent"), col("humidity_percent"),
        lit("line_id"), col("line_id"),
        lit("equipment_id"), col("equipment_id")
    )
)

from pyspark.sql.functions import lit, col, to_date, concat_ws

quality_knowledge_ready_df = quality_with_metadata_df \
    .withColumn("knowledge_id", col("metric_id")) \
    .withColumn("knowledge_type", lit("quality")) \
    .withColumn("business_domain", lit("quality")) \
    .withColumn(
        "source_reference",
        concat_ws(" | ", lit("quality"), col("metric_id"))
    ) \
    .withColumn(
        "event_date",
        to_date(col("inspection_date"))
    )

final_quality_knowledge_df = quality_knowledge_ready_df.select(
    "knowledge_id",
    "knowledge_type",
    "business_domain",
    "content_text",
    "source_reference",
    "event_date",
    "metadata"
)

final_quality_knowledge_df.write \
    .format("delta") \
    .mode("append") \
    .save(
        "abfss://gold-genai@ecomdatastoreproject.dfs.core.windows.net/knowledge/gold_knowledge_assets"
    )