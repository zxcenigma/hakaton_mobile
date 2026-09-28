{{
  config(
    materialized='table',
    description='Per-period health of the game economy: is the allowance sized correctly, are goals reachable, are children hitting walls too often?'
  )
}}

/*
  A game economy for children fails in two opposite ways, and both are invisible
  without this table:

  * **Too generous** — everything is affordable, no trade-off is ever forced, and
    the core lesson («ограниченность ресурсов», ТЗ §2.1) never lands.
  * **Too tight** — essentials are unaffordable however carefully the child
    plans, which ТЗ §2.2 explicitly forbids: an error must stay recoverable.

  `affordability_ratio` is the diagnostic. Below ~1.1 the economy is starving
  players; above ~2.0 nothing is scarce. The healthy band is editorial, and the
  `economy_anomaly` model is trained to flag departures from it — for the
  methodologist, never for the child.
*/

with per_period as (

    select
        period_no,
        count(distinct profile_pseudo_id)       as active_profiles,

        avg(available_total)                    as avg_available,
        median(available_total)                 as median_available,
        avg(coins_earned)                       as avg_earned,
        avg(coins_spent)                        as avg_spent,
        avg(leftover)                           as avg_leftover,
        median(leftover)                        as median_leftover,

        avg(essential_coverage)                 as avg_essential_coverage,
        avg(plan_adherence)                     as avg_plan_adherence,
        avg(coalesce(savings_rate, 0))          as avg_savings_rate,

        sum(rejected_purchases)                 as total_rejections,
        {{ safe_divide('sum(rejected_purchases)', 'count(*)') }}
                                                as rejections_per_period,
        {{ safe_divide("count(*) filter (where hit_a_limit)", 'count(*)') }}
                                                as share_hitting_limit,
        {{ safe_divide("count(*) filter (where essentials_covered)", 'count(*)') }}
                                                as share_essentials_covered,
        {{ safe_divide("count(*) filter (where saved_this_period)", 'count(*)') }}
                                                as share_saving

    from {{ ref('mart_period_summary') }}
    group by 1

),

essential_cost as (

    -- What one period of mandatory needs actually costs, measured from
    -- behaviour rather than assumed from the catalogue.
    select
        period_no,
        median(actual_essential) as median_essential_spend
    from {{ ref('mart_period_summary') }}
    where essentials_covered
    group by 1

)

select
    p.period_no,
    p.active_profiles,

    p.avg_available,
    p.median_available,
    p.avg_earned,
    p.avg_spent,
    p.avg_leftover,
    p.median_leftover,

    e.median_essential_spend,
    {{ safe_divide('p.median_available', 'nullif(e.median_essential_spend, 0)') }}
        as affordability_ratio,

    p.avg_essential_coverage,
    p.avg_plan_adherence,
    p.avg_savings_rate,

    p.total_rejections,
    p.rejections_per_period,
    p.share_hitting_limit,
    p.share_essentials_covered,
    p.share_saving,

    -- Plain-language verdicts. An anomaly detector proposes; these thresholds,
    -- reviewed by a human, decide.
    {{ safe_divide('p.median_available', 'nullif(e.median_essential_spend, 0)') }} < 1.10
        as flag_economy_too_tight,
    {{ safe_divide('p.median_available', 'nullif(e.median_essential_spend, 0)') }} > 2.00
        as flag_economy_too_loose,
    p.share_essentials_covered < 0.60
        as flag_essentials_unreachable,
    p.share_saving < 0.30
        as flag_saving_not_landing

from per_period p
left join essential_cost e on e.period_no = p.period_no
