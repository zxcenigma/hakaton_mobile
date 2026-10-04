# Alexey Chervak — CV (English)

Готово к переносу в документ. Под международные и стартап-вакансии: без фото,
возраста и семейного положения — на Западе это не принято и иногда прямо
мешает (политика недискриминации не позволяет рекрутеру такое хранить).

Личные данные заполни сам там, где отмечено.

---

**ALEXEY CHERVAK**
Senior Data Engineer → MLOps
Moscow, Russia · Open to remote
+7 993 622-81-82 · chervak_2016@mail.ru · Telegram @dobrycode
GitHub: `‹вставь ссылку›` · LinkedIn: `‹вставь ссылку›`

---

## Summary

Senior Data Engineer with 4+ years building high-load ETL/ELT platforms for
banking and telecom (Sber, MTS, EY). I make data arrive on time, survive
failure and stay trustworthy: terabyte-scale Spark on Hadoop, exactly-once
streaming on Kafka, Airflow pipelines under SLA, and data-quality gates that
block publication rather than warn about it.

Currently moving into MLOps. Built an end-to-end ML platform as an open-source
side project — model registry with quality gates and champion/challenger
promotion, ONNX export with parity verification, drift monitoring, and Airflow
orchestrating the same container image that serves production.

---

## Experience

### Senior Data Engineer — MTS (Telecom)
*April 2026 – July 2026 · Moscow*

Owned ETL pipelines processing telecom data on Apache Airflow within a Hadoop
ecosystem; responsible for DAG stability, data quality and computation speed at
scale.

- **Cut key pipeline runtime by ~40 %** (≈3 h → ≈1.5 h) by rewriting Spark SQL:
  rebuilt joins, added caching, eliminated data skew.
- **Reduced bad data reaching consumers to < 0.5 %** by embedding data-quality
  checks into the DAGs — rejection moved to ingestion instead of discovery
  downstream.
- **Cut DAG failures and manual restarts from ~10/week to isolated incidents**
  through idempotency and explicit error handling.

*Stack: Apache Airflow, Apache Spark, PySpark, Hadoop (HDFS, YARN), Python,
Spark SQL, Git.*

### Senior Data Engineer — Sber (Banking)
*September 2024 – March 2026 · Moscow*

High-load data platform for credit-risk calculation, scoring metrics, anomaly
detection and regulatory reporting. Combined heterogeneous sources, served both
streaming and batch workloads, and held SLAs on business-critical computations.
Acted as tech lead for a workstream.

- **Accelerated critical data marts by 60 %** (≈2 h → ≈45 min) through Spark
  tuning: partitioning, broadcast joins, data-skew elimination, SQL rewritten
  against the execution plan.
- **Scaled processing to 10+ TB/day and raised SLA attainment to 99.9 %**
  (from ~95 % with regular breaches) with fault-tolerant Airflow pipelines and
  explicit dependency management.
- **Reduced data-delivery latency from hours to under a minute** by replacing
  hourly batch with Kafka + Spark Structured Streaming, exactly-once semantics.
- **Cut production data incidents by ~80 %** (from 5–7/month) with a DQ
  framework that *blocks publication* on completeness, correctness and
  uniqueness failures rather than alerting after the fact.
- **Reduced time-to-production for new pipelines from 2–3 days to hours** by
  replacing manual deployment with Jenkins CI/CD plus SLA/DQ alerting in
  Grafana and Prometheus.
- As tech lead: mentoring, pair programming and code review **halved engineer
  onboarding time** (≈5 weeks → ≈2).

*Stack: Python, PySpark, Scala, Apache Spark, Spark Structured Streaming,
Apache Kafka, Hadoop (HDFS, YARN), Apache Airflow, PostgreSQL, ClickHouse,
Hive, SQL, Jenkins, Git, Nexus, Grafana, Prometheus.*

### Data Engineer — EY Russia (Consulting)
*December 2021 – July 2024 · Moscow*

Built and maintained data warehouses and ETL processes for financial and
management consulting engagements. The platform integrated heterogeneous client
sources, automated business logic and produced analytical reporting.

- **Cut heavy reporting queries from ~15 min to ~2 min** through indexing,
  stored-procedure refactoring and schema redesign (MS SQL, PostgreSQL).
- **Eliminated ~70 % of manual data handling** by automating migration and
  transformation in Apache NiFi.
- **Reduced ETL regressions** by introducing GitFlow and code review for SQL
  and pipeline configuration, which previously shipped unreviewed.

*Stack: Python, SQL, MS SQL, PostgreSQL, Apache NiFi, Greenplum, S3, Docker,
Git, ETL, DWH, CI/CD.*

---

## Side project — ML platform (open source)

A data and ML platform for a children's financial-literacy mobile app, built
end to end. Written to production standards rather than as a demo.

- **Two ingestion paths, one contract.** Kafka consumer and HTTP endpoint share
  a single validation function — two validators drift, and the one that drifts
  starts accepting what it must not.
- **Model registry with gates.** A model is not promoted unless it clears an
  absolute threshold *and* is no worse than the incumbent — otherwise every
  retrain is a coin flip that can silently degrade production.
- **ONNX export with parity verification.** Caught a real defect: a regressor
  trained on float64 and served on float32 diverged on 4.2 % of rows.
- **Applicability bounds derived from data.** Accuracy decays from 0.83 to 0.46
  across periods as behavioural archetypes converge; beyond the measured
  horizon the model abstains instead of guessing, and rules answer.
- **Airflow orchestrates containers, not imports.** The orchestrator runs the
  same image that serves production, which removed a dependency-conflict class
  permanently.
- **Serving latency: 0.5 ms median, 1.5 ms p95** against a 50 ms budget —
  down from 527 ms before moving to ONNX Runtime.

341 tests, 82 % coverage, 58 dbt data tests, 14 data-quality checks.

*Stack: Python 3.12, DuckDB, dbt, Apache Iceberg, Trino, Redpanda, Apache
Airflow, MLflow, FastAPI, ONNX Runtime, Docker Compose.*

---

## Education

**MSc, Organisation and Management of High-Tech Production** — MIREA Russian
Technological University, Moscow, 2024

**BSc, Optical Engineering** — Bauman Moscow State Technical University,
Moscow, 2022

---

## Skills

**Data engineering** — Apache Spark, PySpark, Spark Structured Streaming,
Apache Kafka, Hadoop (HDFS, YARN), Apache Airflow, Apache NiFi, dbt, ETL/ELT,
DWH design, Data Quality, Data Contracts

**Databases** — PostgreSQL, ClickHouse, Greenplum, Hive, MS SQL, DuckDB,
Apache Iceberg, Trino

**ML/MLOps** — MLflow, ONNX Runtime, model registry, quality gates,
champion/challenger promotion, drift monitoring (PSI), scikit-learn

**Platform** — Docker, CI/CD (Jenkins, GitHub Actions), Git/GitFlow, Grafana,
Prometheus, Linux, FastAPI

**Languages** — Python, SQL, Scala

**Spoken** — Russian (native), English (`‹укажи уровень — B1/B2›`, technical
documentation)

---

## Заметки для тебя — не вставлять в CV

**Про английский.** Строку про уровень заполни честно. Если читаешь
документацию, но говоришь с трудом — так и пиши: «English — B1, fluent reading
of technical documentation». В стартапах это нормально; выдуманный Upper-
Intermediate вскроется на первом же созвоне.

**Про GitHub.** Ссылка обязательна. Для MLOps-ролей профиль смотрят раньше
резюме.

**Про четыре месяца в МТС.** В английском CV это заметно так же. Приготовь
одну спокойную фразу — не оправдание, а факт.

**Что НЕ дописывать:** Kubernetes, GPU, vLLM, Triton, Kubeflow. Их нет. После
того как построишь (см. `cv-review.md`, п. 5) — допишешь.
