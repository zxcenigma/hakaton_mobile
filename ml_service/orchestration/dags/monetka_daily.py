"""Ежедневный конвейер: bronze → silver → gold → quality → train → export.

Порядок задаёт одно правило: **ничего ниже по течению не выполняется на данных,
не прошедших проверки.** Контроль качества стоит между gold и обучением, а не
рядом с ним, поэтому регрессия в складе не может тихо стать регрессией в
модели, которая потом уедет на телефон ребёнка.

Расписание учитывает офлайн-first: события приходят через дни после того, как
произошли (планшет, который лежал без сети). Запуск не считает вчерашний день
завершённым — он переобрабатывает скользящее окно и опирается на то, что
слияние в bronze идемпотентно. Это дешевле и надёжнее, чем угадывать, когда
партиция «готова».

Почему задачи запускают контейнер, а не импортируют пакет
---------------------------------------------------------
Так было раньше, и образ Airflow из-за этого не собирался: Airflow закрепляет
большую часть дерева зависимостей, платформе нужен pandas новее закреплённого.
Подбор версий здесь — тупик, который придётся проходить заново при каждом
обновлении любой из сторон.

Оркестратору не нужны зависимости конвейера. Ему нужно запустить шаг и узнать,
чем тот закончился. Поэтому каждая задача запускает тот же образ, что работает
в продакшене, и падает, если команда вернула ненулевой код. Побочный эффект
приятный: оркеструется ровно то, что поедет, а не отдельная копия с другими
версиями библиотек.
"""

from __future__ import annotations

import os

import pendulum
from airflow.decorators import dag
from airflow.operators.empty import EmptyOperator
from airflow.providers.docker.operators.docker import DockerOperator

#: Сколько дней назад переобрабатывает каждый запуск. Размер взят из
#: наблюдаемого хвоста доставки: около 2 % событий приходят позже 72 часов и
#: практически ничего — позже недели (`monetka quality` → late_arrival).
LOOKBACK_DAYS = 7

#: Образ конвейера. Тот же, что обслуживает API: один артефакт, одна сборка.
PIPELINE_IMAGE = os.environ.get("MONETKA_PIPELINE_IMAGE", "monetka-api:latest")

#: Путь к каталогу данных **на хосте**. DockerOperator просит демон поднять
#: соседний контейнер, и монтирование разрешается хостом, а не Airflow'ом, —
#: поэтому путь нужен хостовый, а не тот, что виден внутри Airflow.
HOST_DATA_DIR = os.environ.get("MONETKA_HOST_DATA_DIR", "/root/monetka/data")
HOST_ARTIFACTS_DIR = os.environ.get("MONETKA_HOST_ARTIFACTS_DIR", "/root/monetka/artifacts")

DEFAULT_ARGS = {
    "owner": "monetka-data",
    "retries": 2,
    "retry_delay": pendulum.duration(minutes=5),
    "email_on_failure": False,
    "depends_on_past": False,
}


def stage(task_id: str, command: str, *, retries: int | None = None) -> DockerOperator:
    """Один шаг конвейера как запуск контейнера.

    `auto_remove` обязателен: без него каждый запуск DAG оставляет контейнер, и
    через месяц диск кончается не из-за данных.
    """
    return DockerOperator(
        task_id=task_id,
        image=PIPELINE_IMAGE,
        command=command,
        docker_url="unix://var/run/docker.sock",
        network_mode="monetka_default",
        auto_remove="success",
        mount_tmp_dir=False,
        mounts=[
            {"Source": HOST_DATA_DIR, "Target": "/app/data", "Type": "bind"},
            {"Source": HOST_ARTIFACTS_DIR, "Target": "/app/artifacts", "Type": "bind"},
        ],
        environment={"MONETKA_RUN_MODE": "compose"},
        retries=DEFAULT_ARGS["retries"] if retries is None else retries,
    )


@dag(
    dag_id="monetka_daily",
    description="Bronze → silver → gold → quality → train → export",
    schedule="0 3 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["monetka", "elt", "ml"],
    doc_md=__doc__,
)
def monetka_daily() -> None:
    start = EmptyOperator(task_id="start")

    # Идемпотентно по `event_id`, поэтому перекрывающиеся окна ничего не стоят.
    ingest_bronze = stage("ingest_bronze", "monetka bronze")
    build_silver = stage("build_silver", "monetka silver")

    # Внутри прогоняются 58 проверок dbt: витрина с регрессией не доедет до
    # обучения.
    build_gold = stage("build_gold", "monetka gold")

    # Жёсткий гейт. Всё ниже не выполняется, если он не прошёл. Повторять
    # бессмысленно: данные от повтора не исправятся, а сообщение об ошибке
    # потеряется среди попыток.
    run_quality = stage("run_quality", "monetka quality --fail-fast", retries=0)

    # Модель, не прошедшая порог, не выкладывается — команда вернёт ненулевой
    # код, и задача упадёт.
    train_models = stage("train_models", "monetka train --model all", retries=0)

    # Проверка паритета внутри: если экспортированный артефакт расходится с
    # проверенной моделью, шаг падает и на устройство ничего не уезжает.
    export_models = stage("export_models", "monetka export", retries=0)

    monitor = stage("monitor", "monetka monitor")
    finish = EmptyOperator(task_id="finish")

    (
        start
        >> ingest_bronze
        >> build_silver
        >> build_gold
        >> run_quality
        >> train_models
        >> export_models
        >> monitor
        >> finish
    )


monetka_daily()
