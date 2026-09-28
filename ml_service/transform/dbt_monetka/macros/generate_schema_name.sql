{#
  dbt's default behaviour concatenates the target schema with the custom one,
  producing `main_gold` on DuckDB. The ingestion layer, the quality checks and
  the serving API all address the layer as plain `gold`, and the Trino target
  uses real schemas, so the concatenation would make local and compose runs
  disagree about table names.

  Overriding this macro makes the custom schema authoritative: `+schema: gold`
  means `gold`, on every adapter.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
