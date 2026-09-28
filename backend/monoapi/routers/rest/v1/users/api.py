from typing import Annotated

from fastapi import APIRouter, status, Depends

from monoapi.auth.security import oauth2_scheme
from monoapi.routers.exceptions import UnauthorizedResponse


from monoapi.routers.services.users import (
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
    token: Annotated[str, Depends(oauth2_scheme)],
) -> GetUserMeResponse:
    service: GetUserMeService = GetUserMeService(token=token)
    return await service()
