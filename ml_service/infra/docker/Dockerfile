# Multi-stage build for the Monetka platform image.
#
# The runtime stage carries no build toolchain and runs as a non-root user —
# ТЗ §3.4 asks for a reproducible build with no secrets in the image, and a
# container that can write to its own source tree is an easy way to lose both.

# ---------------------------------------------------------------- builder --
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# build-essential is needed by confluent-kafka and lightgbm wheels on slim.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential librdkafka-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip setuptools wheel

# Dependencies are installed from `pyproject.toml` alone, before any source is
# copied. That keeps the expensive layer — the full resolve and download of
# dbt, MLflow, ONNX, Arrow and the rest, around twelve minutes here — keyed on
# the dependency list instead of on the code. Editing a Python file used to
# invalidate it and repeat the whole install.
#
# The stub package exists only so pip has something to install the metadata of;
# it is uninstalled immediately, leaving the dependency tree in the venv.
COPY pyproject.toml README.md ./
RUN mkdir -p src/monetka \
 && touch src/monetka/__init__.py \
 && pip install ".[stream,lake,transform,mlops]" \
 && pip uninstall -y monetka-data-platform

# Now the real source, installed without touching the dependency tree.
COPY src ./src
RUN pip install --no-deps .

# ---------------------------------------------------------------- runtime --
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    MONETKA_RUN_MODE=compose

RUN apt-get update \
 && apt-get install -y --no-install-recommends librdkafka1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system monetka \
 && useradd --system --gid monetka --home /app monetka

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=monetka:monetka src ./src
COPY --chown=monetka:monetka content ./content
COPY --chown=monetka:monetka transform ./transform
# `contracts/` is generated from the event models, and `monetka contracts`
# rewrites it — including inside the container, which is how you check that the
# generation is deterministic. It is output, not source, so it is the one copied
# directory the runtime user may write to.
COPY --chown=monetka:monetka contracts ./contracts
# Read by `monetka stack-check`. Small, and without them that command fails in
# the image with a missing-file error that says nothing about the real cause.
COPY --chown=monetka:monetka infra ./infra
COPY --chown=monetka:monetka docker-compose.yml .env.template ./
# `pyproject.toml` is not decoration here: `_detect_repo_root()` uses it to tell
# a checkout from an installed package. Without it beside the working directory
# the settings fall back to site-packages, which uid 999 cannot write, and the
# API dies during startup.
COPY --chown=monetka:monetka pyproject.toml README.md ./

# dbt refuses to compile anything while `dbt_packages/` is empty, so the
# packages are installed at build time. `ensure_dbt_packages()` would fetch them
# at runtime too, but that would make the first pipeline run depend on the
# network — and inside a container it would write them as the wrong user.
RUN dbt deps --project-dir /app/transform/dbt_monetka --profiles-dir /app/transform/dbt_monetka \
 && chown -R monetka:monetka /app/transform

# Writable paths for artefacts and the local warehouse; both are bind-mounted
# in compose, so this only matters for a standalone run.
#
# `/app/.duckdb` is the third one and the least obvious: the runtime user's home
# is /app, and DuckDB creates `$HOME/.duckdb` for its extensions the first time
# it opens a connection. /app itself stays owned by root — a container that can
# rewrite its own source tree is exactly what the non-root user is for — so the
# one directory DuckDB needs is created here instead. Without it dbt died with
# `IO Error: Failed to create directory "/app/.duckdb": Permission denied`,
# which reads like a dbt problem and is not one.
RUN mkdir -p /app/data /app/artifacts /app/.duckdb \
 && chown -R monetka:monetka /app/data /app/artifacts /app/.duckdb

USER monetka

EXPOSE 8000

# 127.0.0.1, not localhost: this image resolves `localhost` to ::1 as well, and
# uvicorn binds IPv4. Compose overrides this check, but `docker run` does not,
# and a container that reports itself unhealthy while serving traffic is worse
# than one with no check at all.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["monetka", "serve", "--host", "0.0.0.0", "--port", "8000"]
