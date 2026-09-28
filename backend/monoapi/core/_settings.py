from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).parent.parent.parent
FRONTEND_DIR = BACKEND_DIR.parent/"mobile_app"
API_DIR = BACKEND_DIR/"monoapi"
ENV_FILE = (BACKEND_DIR/'.env').resolve()

MODEL_CONFIG: SettingsConfigDict = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class RedisSettings(BaseSettings):
    """
    Класс для настройки соединения с Redis
    """
    
    redis_host: str
    redis_port: str
    redis_db: int
    
    @property
    def redis_url(self) -> str:
        """
        Получает URL для подключения к redis
        """
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    model_config = MODEL_CONFIG


class AuthJWT(BaseSettings):
    """Настройки JWT для аутентификации"""
    keys_path: Path = BACKEND_DIR/'monoapi'/'auth'/'certs'

    private_key_path: Path = keys_path/'jwt-private.pem'
    public_key_path: Path = keys_path/'jwt-public.pem'
    jwt_algorithm: str = Field(description="В контексте закрытых ключей - RS256, если 1 ключ - HS256")

    jwt_available_days: str = Field(description="Дни для refresh токена")
    jwt_access_minutes: str = Field(description="Минуты для access токена")

    model_config = MODEL_CONFIG


class DbSettings(BaseSettings):
    """Настройки базы данных PostgreSQL"""
    pg_user: str
    pg_password: str
    pg_db: str
    pg_host: str
    pg_port: str

    @property
    def db_sync_url(self) -> str:
        return (f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
               f"@{self.pg_host}:{self.pg_port}/{self.pg_db}")
    
    # Используется
    @property
    def db_async_url(self) -> str:
        return (f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
               f"@{self.pg_host}:{self.pg_port}/{self.pg_db}")    

    model_config = MODEL_CONFIG


class DbSessionSettings(BaseSettings):
    """Настройки сессии для подключения к БД"""
    pool_max_overflow: int = Field(description="Доп подключения")
    pool_size: int = Field(description="Дефолт пулл подключений")
    pool_timeout: int
    pool_recycle: int
    
    echo: bool = Field(default=True, description="Смотреть логи (В ПРОДЕ УБРАТЬ)")

    model_config = MODEL_CONFIG


class LoggerSettings(BaseSettings):
    """Настройки логирования"""
    logger_level: int = 20
    logger_path_dir: Path = API_DIR/"logs"

    model_config = MODEL_CONFIG


class FilesSettings(BaseSettings):
    """Пути хранения файлов, загрузок и прочего"""
    catalog_pictures_dir: Path = (
        API_DIR/"public"/"image"
    )


class ServerSettings(BaseSettings):
    """Настройки процесса Uvicorn"""
    model_config = MODEL_CONFIG
    server_port: int
    server_host: str
    server_workers: int = Field(
        default=1, 
        ge=1, 
        description="Колличество воркеров (процессов) для обработки запросов. default: 1"
    )
    server_log_level: str = Field(
        default="info", 
        description="Uvicorn уровни логирования [critical, error, warning, info, debug, trace]"
    )
    server_proxy_headers: bool = Field(
        default=True,
        description="Use X-Forwarded-Proto and X-Forwarded-For headers"
    )
    server_forwarded_allow_ips: str = Field(
        default="*",
        description="Comma-separated list of IPs/networks to trust for forwarded headers"
    )


class Settings(BaseSettings):
    api_name: str
    api_version: str
    api_protocol: str
    cors_origins: list[str] = [
        "*",
    ]

    @property
    def api_url(self) -> str:
        server = self.server_settings
        return f"{self.api_protocol}://{server.server_host}:{server.server_port}"

    server_settings: ServerSettings = ServerSettings()
    
    auth_jwt: AuthJWT = AuthJWT()
    
    redis_settings: RedisSettings = RedisSettings()
    db: DbSettings = DbSettings()
    db_session: DbSessionSettings = DbSessionSettings()

    logger_settings: LoggerSettings = LoggerSettings()
    files_settings: FilesSettings = FilesSettings()

    templates_dir:   Path = API_DIR/"templates"

    apiv1: str = "/api/v1"

    model_config = MODEL_CONFIG


settings: Settings = Settings(_env_file=ENV_FILE, _env_file_encoding="utf-8")
