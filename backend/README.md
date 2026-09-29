# Backend

Запуск API из `backend` после установки зависимостей и настройки `.env`:

```sh
python -m monoapi.run_api
python -m monoapi.run_api --reload
python -m monoapi.run_api --no-reload --workers 2
```

`backend/run.py` пока не используется. `--reload` требует одного worker.
Настройки Uvicorn описаны в `monoapi/web_server/server_config.py`.
Аргументы CLI имеют приоритет над переменными `SERVER_*`.
Значения сервера берутся из `settings.server_settings` (`SERVER_*`).
Основные настройки приложения читаются из `backend/.env`; отдельный файл
настроек сервера, если нужен, — `monoapi/web_server/.env`.

## Docker

Быстрый запуск из корня репозитория:

```bash
bash backend_init.sh up               # поднять всё
bash backend_init.sh up api db redis  # поднять выбранные сервисы
bash backend_init.sh down             # остановить и удалить все контейнеры
bash backend_init.sh down api         # остановить и удалить только API
```

Скрипт создаёт отсутствующие JWT-ключи и `.env`, создаёт внешнюю сеть
и запускает контейнеры через Compose.
Существующие ключи и `.env` сохраняются. Запускать можно из любого каталога.
Docker должен быть доступен текущему пользователю.
UID/GID пользователя передаются при сборке через `APP_UID`/`APP_GID`,
чтобы API мог читать приватный ключ с правами `600`. Запускайте скрипт
от владельца ключей. Для рабочего сервера заполните `.env` своими настройками.

Для ручного запуска:

- Создайте `backend/.env` по примеру `.env.example` и заполните настройки.
- Поместите JWT-ключи `jwt-private.pem` и `jwt-public.pem` в
  `backend/monoapi/auth/certs/`. Каталог монтируется только для чтения;
  файлы должны быть доступны пользователю контейнера.
- Убедитесь, что внешняя сеть `hakaton_mobile_proxy` существует
  (`docker network create hakaton_mobile_proxy`, если её ещё нет).

Из корня репозитория:

```sh
export APP_UID=$(id -u) APP_GID=$(id -g)
docker compose --env-file backend/.env -f backend/docker/docker-compose.yaml config --quiet
docker compose --env-file backend/.env -f backend/docker/docker-compose.yaml up --build -d
```

`--env-file` нужен также для подстановки `PG_USER`, `PG_PASSWORD` и `PG_DB`
в конфигурацию сервиса PostgreSQL. Compose задаёт для API адреса PostgreSQL
и Redis по именам сервисов и адрес прослушивания `0.0.0.0:6767`.
Порт API доступен внутри Docker-сетей; доступ снаружи настраивается через proxy.

Entrypoint выполняет `python -m alembic upgrade head`, затем
`exec python -m monoapi.run_api`. При ошибке миграций API не запускается.
Дополнительные аргументы в `command` сервиса API передаются в `run_api.py`.
Образ не содержит локальную `.venv`, `.env` и JWT-ключи.

`SERVER_FORWARDED_ALLOW_IPS=*` означает доверие proxy-заголовкам от всех
источников. Для ограничения укажите адреса доверенных прокси через запятую.

## Пока не настроено

- В `monoapi/db/migrations/versions` нет миграций: `upgrade head` не создаёт
  таблицы приложения. Healthcheck проверяет запуск API, а не готовность схемы БД.
- Обработчики подтверждения email ещё обращаются к удалённому `email_settings`;
  в Compose нет Celery worker для отправки писем.
- Для ссылок в письмах нужен публичный адрес API: `0.0.0.0` — адрес
  прослушивания сервера, а не адрес для пользователя.
- Для изображений и файловых логов сейчас нет постоянных томов:
  данные внутри контейнера теряются при его пересоздании.

### Обновление только API

```bash
bash backend_init.sh up api
```

Команда пересобирает и запускает только API с `--no-deps`, не запускает
и не пересоздаёт PostgreSQL и Redis. Они должны быть уже запущены.
Для первого запуска всех сервисов используйте `bash backend_init.sh up`.

Данные PostgreSQL находятся в именованном volume `hakaton_mobile_db`.
Скрипт не удаляет volumes, включая при `down`. При запуске API по-прежнему
выполняется `alembic upgrade head`: изменения схемы определяются миграциями.
