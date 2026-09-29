from jwt import ExpiredSignatureError, InvalidTokenError

from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials

from monoapi.auth.utils import (
    encode_jwt,
    decode_jwt
)
#--------------------------------------------------------------------------------
#                HTTPBEARER(ACTUAL IN THIS CASE)
#--------------------------------------------------------------------------------


class AccessTokenBearer(HTTPBearer):
    def __init__(self, auto_error=True):
        super().__init__(auto_error=auto_error)

    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials | None:
        creds = await super().__call__(request)
        if not creds:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Не авторизован",
                headers={"WWW-Authenticate": "Bearer"}
            )

        token = creds.credentials
        
        """
        Try to decode jwt token from header
        """
        try:
            decode_jwt(token)
        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Expired Token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        except InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        return creds


access_token_bearer = AccessTokenBearer()


from typing import ClassVar
from fastapi.security import OAuth2PasswordBearer as _OAuth2PasswordBearer
#--------------------------------------------------------------------------
#                      OAUTH2(NOT ACTUAL IN THIS CASE, JUST FOR INFO)
#--------------------------------------------------------------------------


class OAuth2PasswordBearer(_OAuth2PasswordBearer):
    _token_url: ClassVar[str] = "/auth/token"  # noqa: S105
    _scheme_name = "Bearer"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, tokenUrl=self._token_url, scheme_name=self._scheme_name, **kwargs)


oauth2_scheme = OAuth2PasswordBearer()

