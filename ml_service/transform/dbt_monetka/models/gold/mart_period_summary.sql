{{
  config(
    materialized='table',
    description='One row per profile × closed game period: plan versus fact, pet outcome and every decision the child made in that period.'
  )
}}

/*
  The grain of the whole platform.

  Everything a reviewer wants to ask — «did the plan hold?», «were essentials
  covered?», «did the child save?» — is answerable from this one table, and the
  behaviour features, the adult dashboard and the training set are all derived
  from it rather than re-deriving the joins.

  `plan_adherence` and `essential_coverage` come straight from silver: they are
  shown to the child in the app, so they must be identical numbers computed by
  one plain formula, never recomputed with a different rounding here.
*/

with periods as (

    select *
    from {{ source('silver', 'fct_period') }}
    where {{ exclude_demo() }}

),

purchases as (

    select
        profile_pseudo_id,
        period_no,
        count(*)                                                     as purchases_total,
        count(*) filter (where item_category = 'essential')          as purchases_essential,
        count(*) filter (where item_category = 'optional')           as purchases_optional,
        sum(price)                                                   as coins_spent,
        count(distinct item_id)                                      as distinct_items
    from {{ source('silver', 'fct_purchase') }}
    where {{ exclude_demo() }}
    group by 1, 2

),

rejections as (

    select
        profile_pseudo_id,
        period_no,
        count(*)        as rejected_purchases,
        sum(shortfall)  as total_shortfall,
        max(shortfall)  as max_shortfall
    from {{ source('silver', 'fct_purchase_rejected') }}
    where {{ exclude_demo() }}
    group by 1, 2

),

quests as (

    select
        profile_pseudo_id,
        period_no,
        count(*)                                            as quests_completed,
        count(distinct topic)                               as topics_touched,
        sum(reward)                                         as quest_coins,
        avg(outcome_score)                                  as avg_outcome_score,
        count(*) filter (where outcome = 'optimal')         as optimal_choices,
        avg(attempts)                                       as avg_attempts,
        avg(seconds_spent)                                  as avg_quest_seconds
    from {{ source('silver', 'fct_quest_attempt') }}
    where {{ exclude_demo() }}
    group by 1, 2

),

savings as (

    select
        profile_pseudo_id,
        period_no,
        sum(amount) filter (where direction = 'deposit')        as coins_deposited,
        -sum(amount) filter (where direction = 'withdrawal')    as coins_withdrawn,
        count(*) filter (where direction = 'withdrawal')        as withdrawals,
        max(savings_after)                                      as savings_balance_end
    from {{ source('silver', 'fct_savings') }}
    where {{ exclude_demo() }}
    group by 1, 2

),

income as (

    select
        profile_pseudo_id,
        period_no,
        sum(amount)                                                     as coins_earned,
        sum(amount) filter (where income_source = 'quest_reward')       as coins_from_quests,
        sum(amount) filter (where income_source = 'period_allowance')   as coins_from_allowance,
        sum(amount) filter (where income_source = 'daily_login')        as coins_from_login
    from {{ source('silver', 'fct_income') }}
    where {{ exclude_demo() }}
    group by 1, 2

),

plans as (

    select
        profile_pseudo_id,
        period_no,
        revisions_count,
        seconds_spent   as planning_seconds,
        unallocated
    from {{ source('silver', 'fct_budget_plan') }}
    where {{ exclude_demo() }}

)

select
    p.profile_pseudo_id,
    p.closed_period_no                                      as period_no,
    p.occurred_at                                           as period_closed_at,
    p.event_date                                            as period_closed_date,

    -- ---------------------------------------------------------- plan ------
    p.available_total,
    p.planned_essential,
    p.planned_optional,
    p.planned_savings,
    pl.unallocated,
    pl.revisions_count,
    pl.planning_seconds,

    -- ---------------------------------------------------------- fact ------
    p.actual_essential,
    p.actual_optional,
    p.actual_savings,
    p.leftover,

    -- ------------------------------------------------- headline metrics ---
    p.essential_coverage,
    p.plan_adherence,
    {{ safe_divide('p.actual_optional', 'nullif(p.actual_essential + p.actual_optional, 0)') }}
        as optional_spend_share,
    {{ safe_divide('p.actual_savings', 'nullif(p.available_total, 0)') }}
        as savings_rate,

    -- --------------------------------------------------------- activity ---
    coalesce(pu.purchases_total, 0)         as purchases_total,
    coalesce(pu.purchases_essential, 0)     as purchases_essential,
    coalesce(pu.purchases_optional, 0)      as purchases_optional,
    coalesce(pu.coins_spent, 0)             as coins_spent,
    coalesce(pu.distinct_items, 0)          as distinct_items,

    coalesce(r.rejected_purchases, 0)       as rejected_purchases,
    coalesce(r.total_shortfall, 0)          as total_shortfall,
    coalesce(r.max_shortfall, 0)            as max_shortfall,

    coalesce(q.quests_completed, 0)         as quests_completed,
    coalesce(q.topics_touched, 0)           as topics_touched,
    coalesce(q.optimal_choices, 0)          as optimal_choices,
    q.avg_outcome_score,
    q.avg_attempts,
    q.avg_quest_seconds,
    coalesce(q.quest_coins, 0)              as quest_coins,

    coalesce(s.coins_deposited, 0)          as coins_deposited,
    coalesce(s.coins_withdrawn, 0)          as coins_withdrawn,
    coalesce(s.withdrawals, 0)              as withdrawals,
    s.savings_balance_end,

    coalesce(i.coins_earned, 0)             as coins_earned,
    coalesce(i.coins_from_quests, 0)        as coins_from_quests,
    coalesce(i.coins_from_allowance, 0)     as coins_from_allowance,
    coalesce(i.coins_from_login, 0)         as coins_from_login,

    -- --------------------------------------------- derived flags ----------
    -- Deliberately boolean and boring: these are the columns the adult section
    -- renders, and an adult should be able to read them without a legend.
    p.essential_coverage >= 0.85                        as essentials_covered,
    p.plan_adherence     >= 0.70                        as plan_followed,
    coalesce(s.coins_deposited, 0) > 0                  as saved_this_period,
    coalesce(r.rejected_purchases, 0) > 0               as hit_a_limit

from periods p
left join plans      pl on pl.profile_pseudo_id = p.profile_pseudo_id and pl.period_no = p.closed_period_no
left join purchases  pu on pu.profile_pseudo_id = p.profile_pseudo_id and pu.period_no = p.closed_period_no
left join rejections r  on r.profile_pseudo_id  = p.profile_pseudo_id and r.period_no  = p.closed_period_no
left join quests     q  on q.profile_pseudo_id  = p.profile_pseudo_id and q.period_no  = p.closed_period_no
left join savings    s  on s.profile_pseudo_id  = p.profile_pseudo_id and s.period_no  = p.closed_period_no
left join income     i  on i.profile_pseudo_id  = p.profile_pseudo_id and i.period_no  = p.closed_period_no
