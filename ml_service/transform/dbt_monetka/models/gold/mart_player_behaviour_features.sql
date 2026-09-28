{{
  config(
    materialized='table',
    description='Point-in-time feature table for the behaviour-segment model: one row per profile × period, built only from information available at the close of that period.'
  )
}}

/*
  Training input for `behaviour_segment`.

  Point-in-time correctness is the whole job here. Every window function is
  bounded by `rows between N preceding and current row`, so a row for period 4
  cannot see period 5. Getting this wrong is the classic way to ship a model
  that scores 0.99 offline and is useless on device, so the boundary is stated
  explicitly on every window rather than relying on the default frame.

  What is deliberately NOT a feature:
    * the archetype label — it lives in `data/labels/`, joined only at training
      time, because no such field exists at inference time;
    * anything derived from future periods;
    * anything identifying: no timestamps of real-world activity beyond the
      period ordinal, no device fingerprint, no locale.
*/

with base as (

    select *
    from {{ ref('mart_period_summary') }}

),

windowed as (

    select
        profile_pseudo_id,
        period_no,
        period_closed_at,

        -- ------------------------------------------- current period ------
        essential_coverage,
        plan_adherence,
        coalesce(savings_rate, 0.0)             as savings_rate,
        coalesce(optional_spend_share, 0.0)     as optional_spend_share,
        rejected_purchases,
        withdrawals,
        revisions_count,
        planning_seconds,
        purchases_essential,
        purchases_optional,
        quests_completed,
        coalesce(avg_outcome_score, 0.0)        as quest_outcome_score,
        {{ safe_divide('coins_spent', 'nullif(coins_earned, 0)') }} as spend_to_income_ratio,
        {{ safe_divide('unallocated', 'nullif(available_total, 0)') }} as unallocated_share,

        -- ------------- rolling means over the behaviour window ------------
        -- `var('behaviour_window_periods')` periods including the current one.
        avg(essential_coverage) over w   as avg_essential_coverage_w,
        avg(plan_adherence) over w       as avg_plan_adherence_w,
        avg(coalesce(savings_rate, 0.0)) over w      as avg_savings_rate_w,
        avg(coalesce(optional_spend_share, 0.0)) over w as avg_optional_share_w,

        -- Volatility separates the «explorer» (erratic) from everyone else far
        -- better than any single-period value does.
        coalesce(stddev_samp(plan_adherence) over w, 0.0) as plan_adherence_volatility,

        -- ----------------------- cumulative history ----------------------
        count(*) over cumulative                                     as periods_completed,
        sum(case when saved_this_period then 1 else 0 end) over cumulative as periods_with_savings,
        sum(rejected_purchases) over cumulative                      as cumulative_rejections,
        sum(withdrawals) over cumulative                             as cumulative_withdrawals,
        sum(coins_deposited) over cumulative                         as cumulative_deposited,

        -- Trend: is the child getting better? Positive means improving.
        plan_adherence
          - lag(plan_adherence, 1) over (
                partition by profile_pseudo_id order by period_no
            )                                                        as plan_adherence_delta

    from base
    window
        w as (
            partition by profile_pseudo_id
            order by period_no
            rows between {{ var('behaviour_window_periods') - 1 }} preceding and current row
        ),
        cumulative as (
            partition by profile_pseudo_id
            order by period_no
            rows between unbounded preceding and current row
        )

)

select
    w.*,
    {{ safe_divide('w.periods_with_savings', 'nullif(w.periods_completed, 0)') }}
        as savings_regularity,
    coalesce(w.plan_adherence_delta, 0.0)   as plan_adherence_delta_filled,
    p.pet_combination,
    p.first_android_api_level,

    -- Row is usable for training only once the rolling window is actually full;
    -- earlier rows carry partial windows and would teach the model noise.
    w.period_no >= {{ var('behaviour_window_periods') }} as is_training_eligible

from windowed w
left join {{ source('silver', 'dim_profile') }} p
       on p.profile_pseudo_id = w.profile_pseudo_id
