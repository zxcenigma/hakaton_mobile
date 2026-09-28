{{
  config(
    materialized='table',
    description='Production health of the deployed model and the unbiased outcome comparison between the personalised cohort and the control cohort.'
  )
}}

/*
  The missing half of an ML system.

  Training metrics describe a held-out split of the data the model was fitted
  against. They say nothing about the model that is actually running. This mart
  closes that loop from the one signal the device emits about it: `hint_shown`.

  ---------------------------------------------------------------------------
  Why the grain is the *cohort*, not «did a model choose this hint»
  ---------------------------------------------------------------------------

  The first version of this mart grouped outcomes by `hint_source` — whether a
  model picked the wording. It reported the model arm doing measurably *worse*
  (adherence −0.008 against +0.017, coverage −0.12 against +0.05), which would
  have been a alarming and completely false finding.

  The cause is selection, not the model. A model may only act where the rules
  are indifferent, i.e. for children who are already doing fine. Grouping by
  `hint_source` therefore compares:

      model rows  = children in good shape, with little room to improve
      rule  rows  = everyone else, including children in trouble, who
                    regress towards the mean and so improve a lot

  Two different populations. The comparison measures who received which hint,
  not what the hint did.

  The fix is to compare by `advisor_arm` — the cohort assigned randomly once per
  profile, independent of the child's state. Every profile in the personalised
  cohort is counted whether or not the model ended up acting for them, which is
  an intention-to-treat comparison and is unbiased by construction.

  `hint_source` is still reported, but only for operational questions: how often
  the model actually gets consulted, how fast it answers, what it predicts.

  ---------------------------------------------------------------------------
  On what the outcome numbers do and do not show
  ---------------------------------------------------------------------------

  The data is synthetic and the simulator encodes an assumed hint response. So
  this mart demonstrates that the measurement recovers an effect known to be
  present — it demonstrates nothing about real children. That requires a study
  with the consent of legal representatives (ТЗ §8.4).
*/

with hints as (

    select
        profile_pseudo_id,
        period_no,
        hint_id,
        advisor_arm,
        hint_source,
        model_version,
        predicted_segment,
        inference_latency_ms
    from {{ source('silver', 'fct_hint') }}
    where {{ exclude_demo() }}

),

with_outcome as (

    -- The period *after* the hint: the first chance the child had to act on it.
    -- Joining the same period would measure the state that caused the hint,
    -- which is the tidiest way to accidentally prove a hint works.
    select
        h.*,
        before.plan_adherence     as adherence_before,
        before.essential_coverage as coverage_before,
        after.plan_adherence      as adherence_after,
        after.essential_coverage  as coverage_after,
        after.savings_rate        as savings_rate_after
    from hints h
    left join {{ ref('mart_period_summary') }} before
           on before.profile_pseudo_id = h.profile_pseudo_id
          and before.period_no = h.period_no
    left join {{ ref('mart_period_summary') }} after
           on after.profile_pseudo_id = h.profile_pseudo_id
          and after.period_no = h.period_no + 1

)

select
    period_no,
    advisor_arm,

    -- ===================== outcome: unbiased, by cohort ===================
    -- Every row of the cohort counts, acted on by a model or not.
    count(*)                                          as hints_shown,
    count(distinct profile_pseudo_id)                 as profiles_served,
    avg(adherence_after - adherence_before)           as adherence_delta,
    avg(coverage_after - coverage_before)             as coverage_delta,
    avg(savings_rate_after)                           as savings_rate_after,
    count(*) filter (
        where adherence_after is not null and adherence_before is not null
    )                                                 as outcome_sample_size,

    -- ===================== operational: by actual consult =================
    count(*) filter (where hint_source = 'model')     as model_consults,
    {{ safe_divide("count(*) filter (where hint_source = 'model')", 'count(*)') }}
                                                      as consult_rate,
    count(distinct hint_id)                           as distinct_hints,
    max(model_version)                                as model_version,

    avg(inference_latency_ms)                         as avg_latency_ms,
    quantile_cont(inference_latency_ms, 0.95)         as p95_latency_ms,
    max(inference_latency_ms)                         as max_latency_ms,
    -- ТЗ §3.4 allows a second for a visible response; on-device inference has
    -- to be far quicker than that or the advisor feels broken.
    count(*) filter (where inference_latency_ms > 50) as slow_inferences,

    -- What the model predicted. A collapse onto one class is the earliest
    -- visible sign of a broken feature pipeline, and it shows up here long
    -- before any outcome is available to compare against.
    count(*) filter (where predicted_segment = 'planner')  as predicted_planner,
    count(*) filter (where predicted_segment = 'spender')  as predicted_spender,
    count(*) filter (where predicted_segment = 'saver')    as predicted_saver,
    count(*) filter (where predicted_segment = 'explorer') as predicted_explorer,

    -- Legible flags: a dashboard should not require a statistician.
    quantile_cont(inference_latency_ms, 0.95) > 50    as flag_slow,
    count(distinct hint_id) = 1                       as flag_single_hint_collapse

from with_outcome
group by period_no, advisor_arm
