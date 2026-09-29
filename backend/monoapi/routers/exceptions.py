from pydantic import Field

from monoapi.helpers.pydantic import BaseModel


class NotFoundResponse(BaseModel):
    detail: str = Field("Not Found")


class UnauthorizedResponse(BaseModel):
    detail: str = Field("Unauthorized")