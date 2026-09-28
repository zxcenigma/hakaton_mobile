import argparse

import uvicorn
from pydantic import ValidationError

from monoapi.web_server.server_config import ServerSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Запуск API сервера")
    parser.add_argument("--reload", 
                        action=argparse.BooleanOptionalAction, 
                        default=False,
                        help="Режим разработки (перезапуск при изменении кода). " \
                        "--workers=1, не менять.",)
    
    parser.add_argument("--workers", 
                        type=int, 
                        default=None, 
                        help="Колличество воркеров (процессов) для обработки запросов. " \
                        "default: 1")
    
    parser.add_argument("--log-level",
                        choices=("critical", "error", "warning", "info", "debug", "trace"),
                        default=None,
                        help="Uvicorn уровни логирования [critical, error, warning, info, debug, trace]" \
                        "default: info",)
    
    parser.add_argument("--proxy-headers",
                        action=argparse.BooleanOptionalAction,
                        default=None,
                        help="Use X-Forwarded-Proto and X-Forwarded-For headers",)
    
    parser.add_argument("--forwarded-allow-ips",
                        default=None,
                        help="Comma-separated trusted proxy IPs/networks, or '*' to trust all",)
    args = parser.parse_args()

    inputs = {key: value for key, value in vars(args).items() if value is not None}
    try:
        config = ServerSettings(**inputs)
    except ValidationError as exc:
        parser.error(str(exc))

    uvicorn.run("monoapi:app", **config.model_dump())


if __name__ == "__main__":
    main()
