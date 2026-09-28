# Набор тест-кейсов

Требуется ТЗ §5.10 — «набор тест-кейсов и краткий отчёт о проверке на
физическом устройстве».

**Граница.** Этот документ покрывает дата- и ML-платформу. Тест-кейсы самого
приложения (прохождение обязательного сценария Приложения А на физическом
Android-устройстве) ведёт команда приложения — платформа их не заменяет.

Все кейсы ниже **автоматизированы**: ID соответствует имени теста, который можно
запустить и увидеть падение. Кейс без исполняемого теста в этот список не
включён.

```bash
pytest                       # все кейсы
pytest -m "not slow"         # без обучения моделей
```

---

## 1. Контракты событий и приватность

| ID | Проверка | Ожидаемый результат | Тест |
|:---|:---|:---|:---|
| TC-1.1 | Поле с персональными данными в payload | Событие отклонено | `test_personal_data_fields_are_rejected` |
| TC-1.2 | Безопасное поле, содержащее подстроку из чёрного списка (`cumulative`, `volatility`) | Не срабатывает | `test_safe_fields_are_not_flagged` |
| TC-1.3 | Персональные данные во вложенном объекте | Отклонено с указанием пути | `test_privacy_guard_recurses_into_nested_objects` |
| TC-1.4 | Аудит всех колонок хранилища | Ни одной колонки с персональными данными | `test_no_personal_data_columns_anywhere` |
| TC-1.5 | Опубликованные схемы контрактов | Нет полей с персональными данными | `test_published_schemas_carry_no_personal_data` |
| TC-1.6 | Событие без часового пояса | Отклонено | `test_occurred_at_must_be_timezone_aware` |
| TC-1.7 | Android API ниже 26 | Отклонено (ТЗ §3.1.1) | `test_android_api_level_floor_matches_tz` |
| TC-1.8 | Новое событие без контракта payload | Тест падает | `test_every_event_has_a_payload_contract` |

## 2. Инварианты игровой экономики

| ID | Проверка | Ожидаемый результат | Тест |
|:---|:---|:---|:---|
| TC-2.1 | Покупка, где баланс не сходится | Отклонена контрактом | `test_purchase_balance_must_close` |
| TC-2.2 | Отрицательный баланс | Непредставим на уровне типа (ТЗ §2.5.6) | `test_negative_balance_is_unrepresentable` |
| TC-2.3 | План превышает доступную сумму | Отклонён (ТЗ §2.5.5) | `test_plan_cannot_exceed_available_budget` |
| TC-2.4 | Снятие из копилки без подтверждения | Непредставимо (ТЗ §2.5.7) | `test_withdrawal_requires_explicit_confirmation` |
| TC-2.5 | Соответствие плану при полном совпадении | Ровно 1.0 | `test_plan_adherence_is_one_when_fact_matches_plan` |
| TC-2.6 | Соответствие плану при грубом промахе | Не уходит ниже 0 | `test_plan_adherence_never_goes_below_zero` |
| TC-2.7 | Монеты появляются из ниоткуда (испорченные данные) | Проверка качества падает | `test_broken_purchase_arithmetic_is_detected` |
| TC-2.8 | Стадия питомца понижается | Проверка падает (ТЗ §2) | `test_stage_regression_is_detected` |
| TC-2.9 | Состояние питомца ниже пола | Проверка падает | `test_pet_state_below_floor_is_detected` |
| TC-2.10 | Период закрыт без плана | Проверка падает | `test_period_without_a_plan_is_detected` |

## 3. Учебный контент

| ID | Проверка | Ожидаемый результат | Тест |
|:---|:---|:---|:---|
| TC-3.1 | Минимумы ТЗ §2.6 по декларации | ≥8 позиций, ≥6 заданий, ≥3 темы, ≥3 цели, ≥3 стадии | `test_catalogue_meets_minimum` и далее |
| TC-3.2 | Минимумы ТЗ §2.6 **по фактическим данным** | 27 комбинаций, 9 заданий, 14 позиций, 5 целей | `test_tz_content_minimums_are_met_from_observed_data` |
| TC-3.3 | Вариант задания без объяснения | Тест падает (ТЗ §2.5.8) | `test_every_quest_choice_explains_itself` |
| TC-3.4 | Неудачный вариант не приносит награды | Тест падает (ТЗ §3.5, тон) | `test_poor_choices_still_earn_something` |
| TC-3.5 | Стыдящая или пугающая формулировка | Тест падает | `test_no_shaming_or_frightening_language` |
| TC-3.6 | Арифметика задания вне возрастной нормы | Тест падает | `test_arithmetic_is_age_appropriate` |
| TC-3.7 | Покупка способна увести состояние через весь диапазон | Тест падает (ТЗ §2.2) | `test_no_unrecoverable_effects` |
| TC-3.8 | Требования к стадиям не монотонны | Тест падает | `test_stage_requirements_are_monotonic` |

## 4. Конвейер данных

| ID | Проверка | Ожидаемый результат | Тест |
|:---|:---|:---|:---|
| TC-4.1 | Повторная загрузка bronze | Ноль новых строк, все дубликаты | `test_bronze_load_is_idempotent` |
| TC-4.2 | Пересборка silver на неизменном bronze | Идентичные счётчики | `test_silver_rebuild_is_stable` |
| TC-4.3 | Идентификаторы событий | Уникальны | `test_event_ids_are_unique` |
| TC-4.4 | Ссылочная целостность с контент-паком | Нет сирот | `test_referential_integrity_against_the_content_pack` |
| TC-4.5 | Некорректное сообщение в потоке | Уходит в DLQ с причиной, консьюмер жив | `test_stream_parse_rejects_malformed_json` |
| TC-4.6 | Персональные данные в потоке | Отклонены (не только в батче) | `test_stream_parse_rejects_personal_data` |
| TC-4.7 | Время доставки в бэкфилле | Сохраняется, не затирается «сейчас» | `test_stream_parse_preserves_supplied_ingested_at` |
| TC-4.8 | Проверка качества, которая падает с ошибкой | Попадает в отчёт как провал, а не исчезает | `test_a_raising_check_is_reported_as_a_failure` |

## 5. Модели и экспорт на устройство

| ID | Проверка | Ожидаемый результат | Тест |
|:---|:---|:---|:---|
| TC-5.1 | Профиль в обучающей и тестовой выборке одновременно | Невозможно | `test_split_never_leaks_a_profile` |
| TC-5.2 | Воспроизводимость обучения | Те же метрики при повторе | `test_behaviour_model_metrics_are_reproducible` |
| TC-5.3 | Порядок строк из хранилища | Стабилен между процессами | `test_behaviour_frame_row_order_is_stable` |
| TC-5.4 | Модель не превосходит базовую линию | Гейт не пройден, модель не публикуется | `test_behaviour_model_beats_its_baseline` |
| TC-5.5 | Модель, не прошедшая гейт | Не становится `latest` | `test_failing_model_is_not_promoted` |
| TC-5.6 | Паритет ONNX против sklearn | Метки точно, решения ≥0.999 | `test_onnx_export_and_parity` |
| TC-5.7 | Размер артефакта | Меньше 5 МБ — помещается в APK | `test_onnx_export_and_parity` |
| TC-5.8 | Порядок импорта onnxruntime / skl2onnx | Зафиксирован | `test_import_order_is_safe` |
| TC-5.9 | Признак, не объявленный в реестре | Тест падает | `test_every_model_feature_is_declared` |
| TC-5.10 | Предсказание модели равно истинной метке | Тест падает (утечка) | `test_predicted_segment_is_a_prediction_not_the_label` |

## 6. Границы ML (ТЗ §2.7.5, §3.2)

| ID | Проверка | Ожидаемый результат | Тест |
|:---|:---|:---|:---|
| TC-6.1 | Модель пытается перебить подсказку о непокрытом обязательном | Правило побеждает | `test_model_cannot_override_a_concrete_problem` |
| TC-6.2 | Модель ставит максимум самым сложным заданиям новичку | Потолок сложности держится | `test_beginner_is_never_offered_a_hard_quest` |
| TC-6.3 | Модель топит одну тему, остальным даёт −100 | Все три темы в выдаче | `test_a_dominant_model_cannot_starve_a_topic` |
| TC-6.4 | Модель отсутствует | Полная корректная выдача по правилам | `test_recommendation_works_without_a_model` |
| TC-6.5 | Период за горизонтом применимости | Модель отказывается отвечать | `test_model_abstains_beyond_its_validated_horizon` |
| TC-6.6 | Опечатка в имени поля запроса | 422, а не тихое игнорирование | `test_hint_rejects_unknown_fields` |

## 7. API и OpenAPI

| ID | Проверка | Ожидаемый результат | Тест |
|:---|:---|:---|:---|
| TC-7.1 | Спецификация OpenAPI | Генерируется (ТЗ §3.2) | `test_openapi_spec_is_generated` |
| TC-7.2 | Любая подсказка | Есть текст и следующий шаг (ТЗ §2.5.9) | `test_hint_always_returns_text_and_a_next_step` |
| TC-7.3 | Значение вне диапазона 0–1 | 422 | `test_hint_rejects_out_of_range_values` |
| TC-7.4 | Некорректный идентификатор профиля | 422 | `test_adult_progress_rejects_a_malformed_id` |

## 8. Инфраструктура и эксплуатация

| ID | Проверка | Ожидаемый результат | Тест |
|:---|:---|:---|:---|
| TC-8.1 | Образ в compose на плавающем теге | Тест падает | `test_compose_file_is_valid_and_pins_images` |
| TC-8.2 | Контейнер работает от root | CI падает | шаг `Fail if the image runs as root` |
| TC-8.3 | Алерт без описания действия | Тест падает | `test_every_alert_names_an_action` |
| TC-8.4 | Панель дашборда без описания | Тест падает | `test_dashboard_panels_are_documented` |
| TC-8.5 | Любая команда CLI | `--help` отрабатывает | `test_every_command_has_help` |
| TC-8.6 | Контракты разошлись с моделями | Тест падает | `test_contracts_are_up_to_date` |
| TC-8.7 | Из контракта удалено поле | Тест падает (обратная совместимость) | `test_schema_change_is_backwards_compatible` |
| TC-8.8 | Секрет в истории git | CI падает | шаг `gitleaks` |

---

## Отчёт о проверке

**Среда:** Windows 10 (10.0.19044), Python 3.12.10, DuckDB 1.x, dbt 1.12.5
с адаптером duckdb 1.11.0.

| Показатель | Значение |
|:---|:---|
| Автотестов | 221 |
| Покрытие кода | 83% |
| Тестов dbt | 59 |
| Проверок качества данных | 14 |
| Прогонов подряд без флаков | 3 |

**Проверено вручную:** полный прогон `monetka demo` с чистого состояния,
рендер презентации через установленный PowerPoint, валидность SVG-баннеров
в браузере.

**Не проверено запуском:**

* контейнерный стек `docker compose` — Docker на машине сборки не установлен;
* Dart-интеграция `app-integration/lib/monetka_advisor.dart` — нет Flutter SDK;
* путь Kafka в рантайме — покрыт только модульными тестами разбора сообщений.

Эти три пункта названы прямо, а не выданы за проверенные.
