"""Настройки процесса Uvicorn, независимые от импорта приложения."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from monoapi.core import settings


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SERVER_",
        env_file=Path(__file__).resolve().parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = settings.server_settings.server_host
    port: int = settings.server_settings.server_port
    reload: bool = False
    workers: int = Field(default=settings.server_settings.server_workers, ge=1)
    log_level: Literal["critical", "error", "warning", "info", "debug", "trace"] = settings.server_settings.server_log_level
    proxy_headers: bool = settings.server_settings.server_proxy_headers
    forwarded_allow_ips: str = settings.server_settings.server_forwarded_allow_ips

    @model_validator(mode="after")
    def validate_process_mode(self) -> Self:
        if self.reload and self.workers != 1:
            raise ValueError("SERVER_RELOAD требует SERVER_WORKERS=1, " \
                             f"а у вас SERVER_WORKERS={self.workers}")
        return self
