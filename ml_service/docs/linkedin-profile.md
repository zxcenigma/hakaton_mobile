# LinkedIn на английском — под стартапы

Готовый текст по полям. Копируй по разделам.

Отличие от резюме: LinkedIn читают по диагонали и чаще с телефона. Headline и
первые две строки About решают, откроют ли остальное. Стартапы ищут не по
должности, а по словам из своего стека — поэтому ключевые термины должны быть
в тексте, а не только в «Skills».

---

## Headline

220 символов. Это то, что видно в поиске рядом с именем.

Вариант под MLOps-стартапы:

> Senior Data Engineer → MLOps | Spark · Kafka · Airflow at 10+ TB/day | Built
> an ML platform end-to-end: model registry, quality gates, ONNX serving at
> 0.5 ms | Open to remote

Вариант, если хочешь остаться ближе к Data Engineering:

> Senior Data Engineer | Terabyte-scale Spark & Kafka, exactly-once streaming,
> SLA 99.9 % | Banking & telecom (Sber, MTS, EY) | Moving into MLOps | Remote

Почему так: цифра в заголовке — единственное, что отличает тебя от сотни
«Senior Data Engineer». «10+ TB/day» и «0.5 ms» запоминаются.

---

## About

Первые две строки видны без нажатия «see more». Поэтому главное — туда.

> I build data platforms that stay correct under load. Four years on
> high-load ETL/ELT for banking and telecom — terabyte-scale Spark on Hadoop,
> exactly-once streaming on Kafka, Airflow pipelines holding 99.9 % SLA.
>
> What I actually optimise for is trust in data. At Sber I cut production
> data incidents by ~80 % with a DQ framework that blocks publication instead
> of alerting after the fact, and brought delivery latency from hours to under
> a minute by replacing hourly batch with Kafka + Spark Structured Streaming.
> At MTS I cut pipeline runtime by 40 % and reduced DAG failures from ~10 a
> week to isolated incidents.
>
> I'm moving into MLOps, and I did it the way I'd want a candidate to: by
> building. My side project is an end-to-end ML platform — model registry with
> quality gates and champion/challenger promotion, ONNX export verified against
> the source model, drift monitoring, and Airflow orchestrating the same
> container image that serves production. 341 tests, 82 % coverage, 0.5 ms
> median serving latency against a 50 ms budget.
>
> Two things I believe about this work. First: a model that clears an absolute
> threshold can still be worse than the one already running, so the gate is
> necessary but never sufficient. Second: the most useful thing a model can do
> at the edge of its competence is abstain — in my project it does, and rules
> answer instead.
>
> Currently learning Kubernetes and LLM inference (vLLM, quantisation) with the
> same approach — building, measuring, writing down the numbers.
>
> Open to remote roles. Russian native, English for technical work.

Подгони последние две строки под правду: если Kubernetes ещё не начал — напиши
«starting with», а не «currently learning».

---

## Experience — как писать здесь

LinkedIn не любит длинные списки. Три-четыре буллета на позицию, остальное —
в резюме.

### Senior Data Engineer · MTS
*Apr 2026 – Jul 2026*

> ETL pipelines on Apache Airflow within a Hadoop ecosystem; owned DAG
> stability, data quality and computation speed.
>
> • Cut key pipeline runtime ~40 % (3 h → 1.5 h) — Spark SQL rewrite, join
> rebuild, data-skew elimination
> • Reduced bad data reaching consumers to < 0.5 % by moving rejection to
> ingestion
> • Cut DAG failures from ~10/week to isolated incidents through idempotency

### Senior Data Engineer · Sber
*Sep 2024 – Mar 2026*

> High-load platform for credit risk, scoring and regulatory reporting.
> Streaming and batch, business-critical SLAs. Tech lead for a workstream.
>
> • Scaled to 10+ TB/day, raised SLA attainment from ~95 % to 99.9 %
> • Cut critical mart runtime 60 % (2 h → 45 min) — partitioning, broadcast
> joins, execution-plan-driven SQL rewrites
> • Brought delivery latency from hours to < 1 min: Kafka + Spark Structured
> Streaming, exactly-once
> • Cut production data incidents ~80 % with a DQ framework that blocks
> publication on failure
> • Time-to-production for new pipelines: 2–3 days → hours (Jenkins CI/CD,
> SLA/DQ alerting)

### Data Engineer · EY Russia
*Dec 2021 – Jul 2024*

> Data warehouses and ETL for financial and management consulting.
>
> • Heavy reporting queries 15 min → 2 min (indexing, stored-procedure
> refactoring, schema redesign)
> • Eliminated ~70 % of manual data handling by automating migration in Apache
> NiFi
> • Introduced GitFlow and code review for SQL and pipeline configuration

---

## Projects — добавь отдельной секцией

LinkedIn позволяет секцию Projects. Для перехода в MLOps она важнее, чем
кажется: это единственное место, где видно, что ты делаешь руками *сейчас*.

**ML Platform for a Financial-Literacy Mobile App** — *open source*

> End-to-end data and ML platform: event contracts, bronze/silver/gold on dbt,
> Iceberg lakehouse queried through Trino, training with quality gates, ONNX
> export verified against the source model, and serving with a guaranteed
> fallback to rules.
>
> Engineering decisions I'd defend in an interview:
> • The orchestrator runs the pipeline as containers rather than importing it —
> Airflow pins a dependency tree that conflicts with the platform's, and
> version-pinning is a dead end you re-enter on every upgrade. Side effect:
> what gets orchestrated is exactly what ships.
> • Applicability bounds derived from measurement, not asserted. Accuracy
> decays 0.83 → 0.46 as behavioural archetypes converge; beyond the horizon the
> model abstains.
> • Parity checking after ONNX conversion caught a float64/float32 divergence
> affecting 4.2 % of rows before it reached devices.
>
> 341 tests, 82 % coverage, 0.5 ms median latency against a 50 ms budget.
> Python, dbt, Iceberg, Trino, Kafka, Airflow, MLflow, ONNX Runtime, Docker.

---

## Skills — порядок имеет значение

LinkedIn показывает первые три, и по ним же работает поиск рекрутёров.
Поставь вперёд то, под что хочешь получать предложения.

Если цель MLOps:

1. MLOps
2. Apache Airflow
3. Apache Spark

Дальше: Apache Kafka, Python, Docker, MLflow, Data Quality, PySpark, SQL,
PostgreSQL, ClickHouse, Hadoop, dbt, CI/CD, Prometheus, Grafana, ETL,
Data Warehousing, ONNX, FastAPI, Linux.

**Не добавляй** Kubernetes, GPU, vLLM, LLM — пока не построишь. В LinkedIn за
навык можно получить подтверждение от коллег, и навык без опыта выглядит
странно именно там.

---

## Open to work

Включи «Open to work» в режиме **только для рекрутёров**, если текущая работа
это требует. Рамка на аватаре отпугивает часть стартапов — они считают, что за
тобой уже очередь, и не пишут.

Укажи: Remote, и роли — `MLOps Engineer`, `Data Engineer`, `Platform Engineer
(Data)`, `Machine Learning Engineer`.

---

## Что делать после заполнения

**Напиши один пост про проект.** Не «я тут сделал», а одна конкретная история —
лучше всего про то, почему модель сама сокращает своё окно, или почему витрина
показала, что модель хуже правил. Технические истории с неочевидным выводом
расходятся лучше анонсов, и именно они приводят в профиль нужных людей.

**Подпишись на людей, а не на компании.** Авторы vLLM, dbt, Airflow,
инженеры из MLOps-стартапов. Комментарий по делу под чужим постом даёт больше
контактов, чем сто откликов.

**Про стартапы отдельно.** Они смотрят GitHub раньше LinkedIn. Приведи в
порядок README проекта — он и есть твоё настоящее резюме для них.
