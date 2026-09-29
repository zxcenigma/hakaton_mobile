from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Form,
    HTTPException,
    Response,
    status,
)

from monoapi.auth.schemas import (
    ResponseSignUp,
    SignInSchema,
    SignUpSchema,
    TokenInfoSchema,
)
from monoapi.auth.services.auth_service import (
    LogoutService,
    RefreshService,
    SignInService,
    SignUpService,
)
from monoapi.core import settings


router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=int(float(settings.auth_jwt.jwt_available_days) * 86400),
        httponly=True,
        secure=settings.api_protocol.lower() == "https",
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.api_protocol.lower() == "https",
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseSignUp,
)
async def sign_up(data: SignUpSchema) -> ResponseSignUp:
    service = SignUpService(request_data=data)
    return await service()

@router.post(
    "/signin",
    status_code=status.HTTP_200_OK,
    response_model=TokenInfoSchema,
)
async def sign_in(
    data: SignInSchema,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenInfoSchema:
    service = SignInService(
        request_data=data,
        current_refresh_token=refresh_token,
    )
    token_info, refresh_token = await service()
    set_refresh_cookie(response, refresh_token)
    return token_info


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=TokenInfoSchema,
)
async def refresh_access_token(
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenInfoSchema:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh cookie отсутствует",
        )
    service = RefreshService(refresh_token=refresh_token)
    return await service()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> None:
    service = LogoutService(refresh_token=refresh_token)
    await service()
    clear_refresh_cookie(response)


@router.post(
    "/token",
    status_code=status.HTTP_200_OK,
    response_model=TokenInfoSchema,
)
async def swagger_token(
    username: Annotated[str, Form()],
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenInfoSchema:
    service = SignInService(
        request_data=SignInSchema(username=username),
        current_refresh_token=refresh_token,
    )
    token_info, refresh_token = await service()
    set_refresh_cookie(response, refresh_token)
    return token_info
