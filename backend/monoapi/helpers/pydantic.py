from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict

from monoapi.core import settings

# from pydash import camel_case
# import pydash



class BaseModel(_BaseModel):
    # model_config = ConfigDict(
    #     from_attributes=True,
    #     populate_by_name=True,
    #     alias_generator=camel_case,
    # )
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    # def to_dict(self, *, by_alias: bool = True, reveal_secrets: bool = False, exclude_unset=False) -> dict:
    #     result: dict = self.model_dump(by_alias=by_alias, exclude_unset=exclude_unset, mode="json")
    #     if not reveal_secrets:
    #         return result

    #     secret_dict: dict = {}
    #     name: str
    #     for name in self.model_fields_set:
    #         field: Any = getattr(self, name)
    #         if isinstance(field, SecretStr):
    #             secret_dict.update(
    #                 {
    #                     name: field.get_secret_value(),
    #                 }
    #             )
    #     return pydash.merge(result, secret_dict)
    