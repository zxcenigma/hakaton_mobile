from datetime import datetime

from pydantic import EmailStr, Field, UUID4

from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services import BaseUserAuthenticatedService


class GetUserMeResponse(BaseModel):
    uuid: UUID4
    username: str = Field(
        min_length=1,
        max_length=24,
    )
    email: EmailStr
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    # is_subscribed: bool
    # is_confirmed: bool


class GetUserMeService(BaseUserAuthenticatedService[GetUserMeResponse]):
    async def process(self, *args, **kwargs) -> GetUserMeResponse:
        return GetUserMeResponse.model_validate(self.user.__dict__)
