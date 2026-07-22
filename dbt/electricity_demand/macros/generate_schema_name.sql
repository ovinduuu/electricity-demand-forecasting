{#
  dbt's default generate_schema_name macro concatenates the profile's base
  schema with a model's custom +schema config (e.g. "electricity_demand_staging"
  + "marts" -> "electricity_demand_staging_marts"). That would silently
  produce datasets nothing else in this project expects - Terraform
  provisions electricity_demand_raw/staging/marts as exact names, and
  src/electricity_demand's serving/pipeline code queries them by those exact
  names. This override makes a custom +schema the dataset name verbatim,
  the standard dbt pattern for exactly this situation.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
