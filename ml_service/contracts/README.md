# Контракты событий

**Сгенерировано.** Не редактировать вручную — правки исчезнут при
следующем `monetka contracts`. Источник истины —
[`src/monetka/common/events.py`](../src/monetka/common/events.py).

Версия схемы: **1**

| Событие | JSON Schema | Avro |
|:---|:---|:---|
| `app_opened` | [json](jsonschema/app_opened.schema.json) | [avsc](avro/app_opened.avsc) |
| `budget_plan_submitted` | [json](jsonschema/budget_plan_submitted.schema.json) | [avsc](avro/budget_plan_submitted.avsc) |
| `goal_reached` | [json](jsonschema/goal_reached.schema.json) | [avsc](avro/goal_reached.avsc) |
| `goal_selected` | [json](jsonschema/goal_selected.schema.json) | [avsc](avro/goal_selected.avsc) |
| `hint_shown` | [json](jsonschema/hint_shown.schema.json) | [avsc](avro/hint_shown.avsc) |
| `income_granted` | [json](jsonschema/income_granted.schema.json) | [avsc](avro/income_granted.avsc) |
| `period_closed` | [json](jsonschema/period_closed.schema.json) | [avsc](avro/period_closed.avsc) |
| `pet_customised` | [json](jsonschema/pet_customised.schema.json) | [avsc](avro/pet_customised.avsc) |
| `pet_stage_changed` | [json](jsonschema/pet_stage_changed.schema.json) | [avsc](avro/pet_stage_changed.avsc) |
| `pet_state_changed` | [json](jsonschema/pet_state_changed.schema.json) | [avsc](avro/pet_state_changed.avsc) |
| `profile_created` | [json](jsonschema/profile_created.schema.json) | [avsc](avro/profile_created.avsc) |
| `purchase_made` | [json](jsonschema/purchase_made.schema.json) | [avsc](avro/purchase_made.avsc) |
| `purchase_rejected` | [json](jsonschema/purchase_rejected.schema.json) | [avsc](avro/purchase_rejected.avsc) |
| `quest_completed` | [json](jsonschema/quest_completed.schema.json) | [avsc](avro/quest_completed.avsc) |
| `quest_started` | [json](jsonschema/quest_started.schema.json) | [avsc](avro/quest_started.avsc) |
| `savings_deposited` | [json](jsonschema/savings_deposited.schema.json) | [avsc](avro/savings_deposited.avsc) |
| `savings_withdrawn` | [json](jsonschema/savings_withdrawn.schema.json) | [avsc](avro/savings_withdrawn.avsc) |
| `telemetry_consent_changed` | [json](jsonschema/telemetry_consent_changed.schema.json) | [avsc](avro/telemetry_consent_changed.avsc) |

Конверт события: [`event_envelope.schema.json`](jsonschema/event_envelope.schema.json).

## Совместимость

Тест `tests/unit/test_contracts.py::test_contracts_are_up_to_date` падает,
если сгенерированные схемы разошлись с моделями. Тест
`test_schema_change_is_backwards_compatible` падает, если из контракта
пропало поле или обязательное поле добавлено без значения по умолчанию —
то есть если новая версия приложения сломает уже собранные данные.

## Почему перечисления выгружены строками

Добавление значения в Avro enum ломает старых потребителей. Закрытость
словаря уже обеспечена контрактом Pydantic и тестами dbt
`accepted_values`, поэтому новое задание или новая позиция каталога не
должны требовать миграции схемы.
