    
import json
import uuid
from datetime import datetime, date

class JSONSerializer:

    def model_to_serializable_dict(self, model) -> dict:
        """
        Преобразует SQLAlchemy-модель в словарь, готовый для JSON-сериализации.
        Обрабатывает: UUID, datetime, date, убирает _sa_instance_state.
        """
        result = {}
        for key, value in model.__dict__.items():
            if key == '_sa_instance_state':
                continue  # пропускаем служебный атрибут SQLAlchemy

            if isinstance(value, uuid.UUID):
                result[key] = str(value)
            elif isinstance(value, (datetime, date)):
                result[key] = value.isoformat()  # преобразуем дату в строку ISO-формата
            elif value is None:
                result[key] = None
            else:
                try:
                    json.dumps({key: value})  # проверяем, сериализуется ли значение
                    result[key] = value
                except (TypeError, OverflowError):
                    # если не сериализуется — преобразуем в строку
                    result[key] = str(value)
        return result


json_helper = JSONSerializer()