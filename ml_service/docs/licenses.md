# Сторонние библиотеки и лицензии

Требуется ТЗ §5.12. Точные версии зафиксированы в
[`pyproject.toml`](../pyproject.toml); установленный состав воспроизводится
командой `pip install -e ".[dev,transform]"`.

## Python — основные зависимости

| Библиотека | Назначение | Лицензия |
|---|---|---|
| pydantic, pydantic-settings | Контракты событий и конфигурация | MIT |
| duckdb | Аналитический движок в local-режиме | MIT |
| pyarrow | Колоночный обмен, bulk-вставка | Apache-2.0 |
| pandas, numpy | Обработка данных | BSD-3-Clause |
| polars | Быстрые преобразования | MIT |
| scikit-learn | Обучение моделей | BSD-3-Clause |
| scipy | Ранговая корреляция | BSD-3-Clause |
| onnx, onnxruntime | Формат и рантайм для устройства | Apache-2.0 / MIT |
| skl2onnx | Конвертация sklearn → ONNX | Apache-2.0 |
| joblib, threadpoolctl | Сериализация моделей, детерминизм обучения | BSD-3-Clause |
| fastapi, uvicorn, starlette | Серверная часть и OpenAPI | MIT / BSD-3-Clause |
| prometheus-client | Метрики | Apache-2.0 |
| structlog | Структурное логирование | MIT / Apache-2.0 |
| typer, rich | CLI | MIT |
| PyYAML | Загрузка контента | MIT |

## Опциональные наборы

| Библиотека | Набор | Лицензия |
|---|---|---|
| confluent-kafka, fastavro | `stream` | Apache-2.0 / MIT |
| s3fs, boto3 | `lake` | Apache-2.0 |
| apache-airflow | `orchestration` | Apache-2.0 |
| dbt-core, dbt-duckdb, dbt-trino | `transform` | Apache-2.0 |
| mlflow | `mlops` | Apache-2.0 |
| pytest, ruff, mypy, pre-commit | `dev` | MIT |

Ранее здесь значились great-expectations, evidently, feast и pyiceberg. Они
удалены из зависимостей — обоснование каждого отказа в
[`pyproject.toml`](../pyproject.toml).

## dbt-пакеты

| Пакет | Лицензия |
|---|---|
| dbt-labs/dbt_utils | Apache-2.0 |

## Образы контейнеров

| Образ | Лицензия / условия |
|---|---|
| python:3.12-slim-bookworm | PSF + Debian |
| redpandadata/redpanda | BSL 1.1 — бесплатно для разработки и тестирования; для промышленной эксплуатации проверить условия |
| chrislusf/seaweedfs | Apache-2.0 |
| amazon/aws-cli | Apache-2.0 |
| tabulario/iceberg-rest | Apache-2.0 |
| trinodb/trino | Apache-2.0 |
| postgres:16-alpine | PostgreSQL License |
| ghcr.io/mlflow/mlflow | Apache-2.0 |
| prom/prometheus | Apache-2.0 |
| grafana/grafana | AGPL-3.0 |

**Замечание о Redpanda и Grafana.** BSL и AGPL накладывают условия при
распространении. Для конкурсного прототипа и локальной разработки ограничений
нет; при выводе в промышленную эксплуатацию эти три компонента нужно либо
заменить (Kafka — Apache-2.0, S3-совместимое хранилище провайдера, Grafana до
версии 7.x или альтернатива), либо выполнить условия лицензий.

**Почему не MinIO.** MinIO закрыл community-образы: любой тег `minio/minio`, включая `latest` и релизы 2022 года, отвечает `denied: requested access to the resource is denied` без аутентификации. Обнаружено при первом реальном запуске стека; заменено на SeaweedFS (Apache-2.0).

## Собственные материалы

Учебный контент в [`content/`](../content/) — тексты заданий, описания позиций
каталога, формулировки целей и объяснений — создан командой и распространяется
вместе с репозиторием под MIT.

Иллюстрации, шрифты и звуки в этой платформе не используются: она не содержит
пользовательского интерфейса. Их права и условия относятся к Android-приложению
и описываются в его документации (ТЗ §5.12, §3.3).

## Материалы организатора

Единая рамка компетенций в области финансовой грамотности и финансовой культуры,
материалы портала «Открытый бюджет города Москвы» и просветительского ресурса
Банка России «Финансовая культура» используются как **источник требований и
терминологии**. Их тексты в репозиторий не включены; ссылки на компетенции
даются идентификаторами в [`competencies.yaml`](../content/competencies.yaml).
