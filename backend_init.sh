#!/bin/bash
set -e
cd "$(dirname "$0")"

usage() {
    echo "Использование: bash backend_init.sh [up|down] [api] [db] [redis]"
}

# Без аргументов — поднять все сервисы.
action=${1:-up}
case "$action" in
    up|down) if [ "$#" -gt 0 ]; then shift; fi ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 1 ;;
esac

# Без списка сервисов команда применяется ко всему проекту.
services=()
for service in "$@"; do
    case "$service" in
        api) services+=(api) ;;
        db) services+=(hakaton_mobile_db) ;;
        redis) services+=(hakaton_mobile_redis) ;;
        *) usage >&2; exit 1 ;;
    esac
done

export APP_UID=$(id -u) APP_GID=$(id -g)
compose=(docker compose --env-file backend/.env -f backend/docker/docker-compose.yaml)

if [ "$action" = down ]; then
    if [ "${#services[@]}" -eq 0 ]; then
        "${compose[@]}" down
    else
        # Удалить только выбранные контейнеры, сохранив сеть и volumes.
        "${compose[@]}" rm --stop --force "${services[@]}"
    fi
    exit 0
fi

# Создать JWT-ключи
certs_dir=backend/monoapi/auth/certs
mkdir -p "$certs_dir"
if [ ! -f "$certs_dir/jwt-private.pem" ]; then
    openssl genrsa -out "$certs_dir/jwt-private.pem" 2048
fi
if [ ! -f "$certs_dir/jwt-public.pem" ]; then
    openssl rsa -in "$certs_dir/jwt-private.pem" -pubout -out "$certs_dir/jwt-public.pem"
fi

# Создать .env
if [ ! -f backend/.env ]; then
    cp backend/.env.example backend/.env
fi

# Запустить сеть и контейнеры
docker network inspect hakaton_mobile_proxy >/dev/null 2>&1 || docker network create hakaton_mobile_proxy
"${compose[@]}" up --build -d "${services[@]}"
