from typing import Annotated

from fastapi import APIRouter, status, Depends

from fastapi.security import HTTPAuthorizationCredentials

from monoapi.auth.security import access_token_bearer
from monoapi.routers.exceptions import UnauthorizedResponse


from monoapi.routers.services.users.get_user_me import (
    GetUserMeResponse,
    GetUserMeService,
)

router = APIRouter(prefix="/users", tags=["users"])

@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=GetUserMeResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": UnauthorizedResponse,
        },
    },
    name="user_me",
)
async def get_me(
    token: Annotated[HTTPAuthorizationCredentials, Depends(access_token_bearer)],
) -> GetUserMeResponse:
    service: GetUserMeService = GetUserMeService(token=token.credentials)
    return await service()
