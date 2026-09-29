import logging

from monoapi.core import settings


class CustomFormatter(logging.Formatter):
    """
    Меняет цвета логов
    Статус: НЕ РАБОТАЕТ (# TODO: пофиксить цвета логов)
    
    """

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def get_logger(name: str) -> logging.Logger:
    """
    Создаёт логгер для файла.
    Пример использования: 

    logger = get_logger(__name__)
    logger.info("Сообщение")
    logger.error("Ошибка")
    """
    logger = logging.getLogger(name)
    logger.setLevel(settings.logger_settings.logger_level)
    if not logger.handlers:
        file_handler   = logging.FileHandler(f"{settings.logger_settings.logger_path_dir/name}.log", mode='w')
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )

        # СЮДА ДОБАВИТЬ ЦВЕТА
        file_handler.setFormatter(formatter) 
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    return logger

