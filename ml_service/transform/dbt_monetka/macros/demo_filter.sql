{#
  Demo-mode traffic exists so experts can replay the mandatory scenario back to
  back without waiting for calendar periods (ТЗ §2.5.13). It is real telemetry,
  but it is not a child playing — including it would inflate every engagement
  metric and poison model training.

  Every gold model therefore filters it out through this one macro, so the rule
  lives in a single place rather than being retyped in each model.
#}
{% macro exclude_demo(relation_alias='') %}
    {%- set prefix = (relation_alias ~ '.') if relation_alias else '' -%}
    {%- if var('exclude_demo_mode', true) -%}
        not {{ prefix }}demo_mode
    {%- else -%}
        true
    {%- endif -%}
{% endmacro %}


{#
  Safe division: returns NULL instead of raising when the denominator is zero.
  Used wherever a rate is computed over a window that may legitimately be empty
  (a player who has closed no periods yet, a quest nobody has attempted).
#}
{% macro safe_divide(numerator, denominator) %}
    case when {{ denominator }} = 0 or {{ denominator }} is null
         then null
         else ({{ numerator }})::double / ({{ denominator }})
    end
{% endmacro %}
