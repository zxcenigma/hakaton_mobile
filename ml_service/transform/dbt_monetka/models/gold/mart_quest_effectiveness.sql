{{
  config(
    materialized='table',
    description='Per-quest teaching effectiveness: how often children get it right, how hard they find it, and whether behaviour improves in the period after they take it.'
  )
}}

/*
  This mart answers the question the methodologist actually has: «is this quest
  teaching anything?»

  `behaviour_lift` is the honest version of that measure — the change in plan
  adherence from the period before the quest to the period after, averaged over
  everyone who took it. It is a correlational number on synthetic data, not a
  causal claim, and the ML card says so plainly. It is useful for spotting a
  quest that is obviously broken (everyone answers optimally ⇒ too easy;
  nobody does ⇒ mis-worded), which is what it is used for.
*/

with attempts as (

    select
        a.profile_pseudo_id,
        a.quest_id,
        a.topic,
        a.difficulty,
        a.outcome,
        a.outcome_score,
        a.attempts,
        a.seconds_spent,
        a.reward,
        a.period_no
    from {{ source('silver', 'fct_quest_attempt') }} a
    where {{ exclude_demo('a') }}

),

adherence_around as (

    select
        qa.quest_id,
        qa.profile_pseudo_id,
        prev_period.plan_adherence as adherence_before,
        next_period.plan_adherence as adherence_after
    from attempts qa
    left join {{ ref('mart_period_summary') }} prev_period
           on prev_period.profile_pseudo_id = qa.profile_pseudo_id
          and prev_period.period_no = qa.period_no - 1
    left join {{ ref('mart_period_summary') }} next_period
           on next_period.profile_pseudo_id = qa.profile_pseudo_id
          and next_period.period_no = qa.period_no + 1

),

lift as (

    select
        quest_id,
        avg(adherence_after - adherence_before) as behaviour_lift,
        count(*) filter (
            where adherence_before is not null and adherence_after is not null
        ) as lift_sample_size
    from adherence_around
    group by 1

)

select
    a.quest_id,
    a.topic,
    a.difficulty,

    count(*)                                            as total_attempts,
    count(distinct a.profile_pseudo_id)                 as distinct_players,

    count(*) filter (where a.outcome = 'optimal')       as optimal_count,
    count(*) filter (where a.outcome = 'suboptimal')    as suboptimal_count,
    count(*) filter (where a.outcome = 'poor')          as poor_count,

    {{ safe_divide("count(*) filter (where a.outcome = 'optimal')", 'count(*)') }}
        as optimal_rate,
    avg(a.outcome_score)                                as avg_outcome_score,
    avg(a.attempts)                                     as avg_attempts,
    avg(a.seconds_spent)                                as avg_seconds_spent,
    median(a.seconds_spent)                             as median_seconds_spent,
    avg(a.reward)                                       as avg_reward,

    l.behaviour_lift,
    l.lift_sample_size,

    -- Content-balance flags for the methodologist. Thresholds are editorial
    -- judgement, not statistics, so they live here in plain sight rather than
    -- inside a model.
    {{ safe_divide("count(*) filter (where a.outcome = 'optimal')", 'count(*)') }} > 0.90
        as flag_too_easy,
    {{ safe_divide("count(*) filter (where a.outcome = 'optimal')", 'count(*)') }} < 0.25
        as flag_too_hard,
    avg(a.seconds_spent) > 240                          as flag_too_slow

from attempts a
left join lift l on l.quest_id = a.quest_id
group by a.quest_id, a.topic, a.difficulty, l.behaviour_lift, l.lift_sample_size
