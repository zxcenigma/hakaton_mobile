#!/bin/sh
set -eu
cd /monoapi
python -m alembic upgrade head
exec python -m monoapi.run_api "$@"
