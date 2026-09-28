{{
  config(
    materialized='table',
    description='Savings progress per profile × goal, including the deterministic periods-to-goal estimate the app shows the child.'
  )
}}

/*
  ТЗ §2.5.7 requires that, if the app shows a time-to-goal, the calculation is
  understandable and based on the average regular top-up. That formula is
  reproduced here *exactly* as the app computes it:

      eta_periods = ceil((cost − saved) / avg_deposit_per_period)

  This mart is the place that proves the app and the warehouse agree. No model
  touches this number — see docs/ml-cards/goal_reachability.md for why the
  reachability model stays offline, in the methodologist's hands.
*/

with selections as (

    select
        profile_pseudo_id,
        goal_id,
        goal_cost,
        min(period_no)      as selected_in_period,
        min(occurred_at)    as selected_at
    from {{ source('silver', 'fct_goal_event') }}
    where goal_event = 'goal_selected'
      and {{ exclude_demo() }}
    group by 1, 2, 3

),

reached as (

    select
        profile_pseudo_id,
        goal_id,
        min(period_no)      as reached_in_period,
        min(occurred_at)    as reached_at,
        min(periods_taken)  as periods_taken
    from {{ source('silver', 'fct_goal_event') }}
    where goal_event = 'goal_reached'
      and {{ exclude_demo() }}
    group by 1, 2

),

flows as (

    select
        profile_pseudo_id,
        goal_id,
        sum(amount) filter (where direction = 'deposit')     as total_deposited,
        -sum(amount) filter (where direction = 'withdrawal') as total_withdrawn,
        count(*) filter (where direction = 'deposit')        as deposit_count,
        count(*) filter (where direction = 'withdrawal')     as withdrawal_count,
        count(distinct period_no) filter (where direction = 'deposit')
                                                             as periods_with_deposit,
        count(distinct period_no)                            as periods_active,
        sum(amount)                                          as net_saved
    from {{ source('silver', 'fct_savings') }}
    where {{ exclude_demo() }}
    group by 1, 2

)

select
    s.profile_pseudo_id,
    s.goal_id,
    s.goal_cost,
    s.selected_in_period,
    s.selected_at,

    coalesce(f.total_deposited, 0)      as total_deposited,
    coalesce(f.total_withdrawn, 0)      as total_withdrawn,
    coalesce(f.net_saved, 0)            as net_saved,
    coalesce(f.deposit_count, 0)        as deposit_count,
    coalesce(f.withdrawal_count, 0)     as withdrawal_count,

    greatest(0, s.goal_cost - coalesce(f.net_saved, 0)) as remaining_to_goal,

    -- Average regular top-up — the denominator ТЗ §2.5.7 names explicitly.
    {{ safe_divide('f.total_deposited', 'nullif(f.periods_with_deposit, 0)') }}
        as avg_deposit_per_period,

    -- The same ceil() the app applies. NULL when the child has never deposited:
    -- showing «∞ periods» to a 7-year-old would be both useless and discouraging,
    -- so the app shows an invitation to make a first deposit instead.
    case
        when coalesce(f.total_deposited, 0) = 0 or coalesce(f.periods_with_deposit, 0) = 0
            then null
        else ceil(
            greatest(0, s.goal_cost - coalesce(f.net_saved, 0))::double
            / ({{ safe_divide('f.total_deposited', 'nullif(f.periods_with_deposit, 0)') }})
        )
    end as eta_periods,

    -- Regularity is what the pedagogy actually cares about (ТЗ §1, компетенция
    -- «регулярно откладывать часть средств») — more than the absolute amount.
    {{ safe_divide('f.periods_with_deposit', 'nullif(f.periods_active, 0)') }}
        as deposit_regularity,

    r.reached_in_period is not null      as is_reached,
    r.reached_in_period,
    r.reached_at,
    r.periods_taken

from selections s
left join flows   f on f.profile_pseudo_id = s.profile_pseudo_id and f.goal_id = s.goal_id
left join reached r on r.profile_pseudo_id = s.profile_pseudo_id and r.goal_id = s.goal_id
