# Runbook

## Быстрая проверка за пять минут

Для эксперта, который видит репозиторий впервые. Ничего, кроме Python 3.11+, не
требуется.

```bash
python -m venv .venv && .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev,transform]"
dbt deps --project-dir transform/dbt_monetka --profiles-dir transform/dbt_monetka
monetka demo
```

Что произойдёт по шагам:

| Шаг | Что делает | Что смотреть |
|---|---|---|
| 1/7 generate | Синтетическая телеметрия | Число событий и меток |
| 2/7 bronze | Загрузка, дедуп, dead-letter | `rejected` должен быть 0 |
| 3/7 silver | Типизация фактов | Число строк по таблицам |
| 4/7 gold | 6 витрин через dbt + 50 тестов | `PASS=50` |
| 5/7 quality | 14 проверок качества и соответствия | Все PASS, в том числе минимумы ТЗ §2.6 |
| 6/7 train | 3 модели с гейтами | Метрики против базовых линий |
| 7/7 export | ONNX + проверка паритета | Размер артефактов и паритет |

Затем:

```bash
monetka serve       # http://localhost:8000/docs
```

## Полный стек

```bash
cp .env.template .env
make up             # лейкхаус + API
make up-full        # плюс Airflow, MLflow, Grafana
```

| Сервис | Адрес | Учётные данные |
|---|---|---|
| API (OpenAPI) | http://localhost:8000/docs | — |
| SeaweedFS master | http://localhost:9333/cluster/status | без пароля |
| Trino | http://localhost:8080 | — |
| Redpanda (Kafka API) | localhost:19092 | — |
| Airflow | http://localhost:8081 | из `.env` |
| MLflow | http://localhost:5000 | — |
| Grafana | http://localhost:3000 | из `.env` |

Учётные данные в `.env.template` — локальные значения по умолчанию, не пригодные
ни для чего за пределами ноутбука. `.env` в `.gitignore`.

## Типичные операции

**Пересобрать всё с нуля**

```bash
make clean-data && make demo
```

**Только витрины после правки SQL**

```bash
monetka gold
```

**Проверить конкретную dbt-модель**

```bash
dbt build --select mart_period_summary+ --project-dir transform/dbt_monetka --profiles-dir transform/dbt_monetka
```

**Обучить одну модель**

```bash
monetka train --model behaviour
```

**Воспроизвести утверждение из документации**

```bash
python -m monetka.ml.diagnostics behaviour-horizon   # таблица падения точности по периодам
python -m monetka.ml.diagnostics quest-ranking       # ранговая корреляция рекомендателя
```

**Откатить модель**

```bash
# указать предыдущую версию
cat artifacts/registry/behaviour_segment/latest.json
# отредактировать на нужную версию, затем
monetka export
```

Либо просто удалить `artifacts/models/behaviour_segment.onnx` — приложение
перейдёт на правила без потери функциональности.

## Диагностика

**`dbt` падает с «Can't open a connection to same database»**

DuckDB допускает одного писателя. Закройте другие процессы, работающие с
`data/warehouse/monetka.duckdb` (в том числе открытый DBeaver или `duckdb` CLI).
Внутри платформы dbt поэтому запускается подпроцессом.

**Экспорт падает без сообщения, код возврата 0xC0000005**

Порядок импорта в `onnx_export.py`: `skl2onnx` обязан импортироваться **до**
`onnxruntime`. Обратный порядок роняет интерпретатор без traceback. Проверяется
тестом `test_import_order_is_safe`.

**`quality` сообщает о 100% опоздавших событий**

Вы загрузили исторический бэкфилл, у которого `ingested_at` проставлен временем
загрузки. Генератор проставляет реалистичную задержку доставки сам; bronze
сохраняет её, если она уже есть в файле.

**Гейт модели не проходит на маленькой выборке**

Это гейт работает правильно. `behaviour_segment` обучается только на периодах
3–5: снизу — `behaviour_window_periods = 3`, раньше скользящее окно неполное;
сверху — `BEHAVIOUR_MAX_PERIOD = 5`, дальше архетипы сходятся и различать их
нечем. Поэтому когорта меньше ~500 игроков даёт несколько сотен строк на 20
признаков и 4 класса. Увеличьте `--players`.

**Проверка паритета ONNX падает**

Сначала посмотрите, какое именно условие не выполнено. Ранговая корреляция около
нуля означает настоящую поломку конвертации — скорее всего, разъехался порядок
признаков. Паритет решений чуть ниже порога при высокой корреляции — это
граничные эффекты float32, смотрите карточку модели.

**Контейнер «unhealthy», хотя сервис отвечает**

Проверка здоровья обращается к `localhost`, а `/etc/hosts` в образе резолвит его
и в `127.0.0.1`, и в `::1`. BusyBox `wget` и клиент Trino идут по IPv6 первыми, а
сервис слушает только IPv4 — соединение отвергается, сервис признаётся больным.
Так упали SeaweedFS и Trino. Во всех проверках адрес указан как `127.0.0.1`
явно; при добавлении сервиса делайте так же.

**Trino выходит при старте, в логе `StaticCatalogManager.loadInitialCatalogs`**

В `infra/trino/catalog/*.properties` есть `${ENV:ПЕРЕМЕННАЯ}`, которой нет в
окружении контейнера. Trino не подставляет пустое значение — он прекращает
запуск. Файл каталога и блок `environment:` сервиса `trino` в
`docker-compose.yml` нужно менять вместе.

**`UnicodeEncodeError: 'charmap' codec can't encode character`**

Консоль Windows в cp1251. CLI переключает свой вывод в UTF-8 сам
(`_force_utf8_output`); если ошибка всё же возникла, вывод идёт мимо CLI —
запустите с `PYTHONIOENCODING=utf-8`.

**Контейнеры падают при `docker compose up` целиком**

Виртуальной машине WSL2 не хватает памяти на одновременный старт. Поднимайте
слоями: сначала `redpanda postgres seaweedfs`, затем `iceberg-rest`, затем
`trino`, затем `api ingestor`. Бюджет по профилям печатает `monetka stack-check`.

## Что запускать перед коммитом

```bash
make lint
make test
```

CI дополнительно прогоняет `monetka demo` целиком, собирает Docker-образ,
проверяет, что контейнер не работает от root, и сканирует всю историю git на
секреты.
