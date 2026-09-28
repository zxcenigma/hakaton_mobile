#!/bin/bash
set -e
cd "$(dirname "$0")"

# Выбрать сервисы (без аргументов — все)
services=()
for service in "$@"; do
    case "$service" in
        api) services+=(hakaton_mobile_api) ;;
        db) services+=(hakaton_mobile_db) ;;
        redis) services+=(hakaton_mobile_redis) ;;
        *) echo "Использование: bash backend_init.sh [api] [db] [redis]" >&2; exit 1 ;;
    esac
done

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
export APP_UID=$(id -u) APP_GID=$(id -g)
docker network inspect hakaton_mobile_proxy >/dev/null 2>&1 || docker network create hakaton_mobile_proxy
docker compose --env-file backend/.env -f backend/docker/docker-compose.yaml up --build -d "${services[@]}"
