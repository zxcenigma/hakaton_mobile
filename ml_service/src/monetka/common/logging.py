"""Structured logging.

JSON in containers (so Loki/Grafana can parse it), human-readable colours on a
developer machine. Configured once, at process entry.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from monetka.common.config import RunMode, get_settings


def configure_logging(force_json: bool | None = None) -> None:
    """Install the structlog pipeline. Idempotent."""
    settings = get_settings()
    as_json = force_json if force_json is not None else settings.run_mode is RunMode.COMPOSE

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if as_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger tagged with the component name."""
    return structlog.get_logger(component=name)
