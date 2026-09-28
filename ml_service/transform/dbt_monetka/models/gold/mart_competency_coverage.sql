{{
  config(
    materialized='table',
    description='Per profile: which financial-literacy competencies the child has actually practised, and how well — the data behind the adult section.'
  )
}}

/*
  This is the mart the protected adult section reads (ТЗ §2.5.12).

  Two rules shape it, both from the specification:

  * «без негативных оценок ребёнка» — there is no score, no grade and no
    ranking. Columns state what was *practised* and what has *not been seen
    yet*, which is actionable without being a judgement.
  * ТЗ §2.5.8 requires all three topics to be present. `topics_covered` makes a
    gap visible so the recommender can close it.

  Mapping from quest to competency lives in `content/competencies.yaml`, seeded
  into `seed_quest_competency` — editing content must never require editing SQL.
*/

with attempts as (

    select
        a.profile_pseudo_id,
        a.quest_id,
        a.topic,
        a.outcome_score,
        a.period_no
    from {{ source('silver', 'fct_quest_attempt') }} a
    where {{ exclude_demo('a') }}

),

by_competency as (

    select
        qa.profile_pseudo_id,
        c.competency_id,
        count(*)                            as attempts,
        count(distinct qa.quest_id)         as distinct_quests,
        avg(qa.outcome_score)               as avg_outcome_score,
        max(qa.period_no)                   as last_practised_period
    from attempts qa
    join {{ ref('seed_quest_competency') }} c on c.quest_id = qa.quest_id
    group by 1, 2

),

by_topic as (

    select
        profile_pseudo_id,
        count(distinct topic)                                       as topics_covered,
        count(distinct topic) filter (where outcome_score >= 1.0)   as topics_mastered,
        count(distinct quest_id)                                    as quests_attempted,
        avg(outcome_score)                                          as overall_outcome_score
    from attempts
    group by 1

),

behaviour as (

    select
        profile_pseudo_id,
        max(period_no)                                              as periods_played,
        avg(essential_coverage)                                     as avg_essential_coverage,
        avg(plan_adherence)                                         as avg_plan_adherence,
        {{ safe_divide("sum(case when saved_this_period then 1 else 0 end)", 'count(*)') }}
                                                                    as savings_regularity
    from {{ ref('mart_period_summary') }}
    group by 1

)

select
    p.profile_pseudo_id,
    coalesce(b.periods_played, 0)       as periods_played,
    coalesce(t.quests_attempted, 0)     as quests_attempted,
    coalesce(t.topics_covered, 0)       as topics_covered,
    coalesce(t.topics_mastered, 0)      as topics_mastered,
    t.overall_outcome_score,

    b.avg_essential_coverage,
    b.avg_plan_adherence,
    b.savings_regularity,

    -- Competency detail as a map: adding a competency to the YAML adds a key
    -- here, with no schema migration and no SQL change.
    map_from_entries(
        list(struct_pack(key := c.competency_id, value := c.avg_outcome_score))
            filter (where c.competency_id is not null)
    ) as competency_scores,

    coalesce(t.topics_covered, 0) >= 3  as all_topics_touched,

    -- Which of the three mandatory topics is still missing. Drives the next-quest
    -- recommendation, and is shown to the adult as a neutral «not seen yet».
    list_sort(
        list_distinct(
            list(c.competency_id) filter (where c.competency_id is not null)
        )
    ) as competencies_practised

from {{ source('silver', 'dim_profile') }} p
left join by_topic      t on t.profile_pseudo_id = p.profile_pseudo_id
left join behaviour     b on b.profile_pseudo_id = p.profile_pseudo_id
left join by_competency c on c.profile_pseudo_id = p.profile_pseudo_id
group by
    p.profile_pseudo_id, b.periods_played, t.quests_attempted, t.topics_covered,
    t.topics_mastered, t.overall_outcome_score, b.avg_essential_coverage,
    b.avg_plan_adherence, b.savings_regularity
