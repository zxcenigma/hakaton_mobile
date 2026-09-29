from jwt import ExpiredSignatureError, InvalidTokenError

from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials

from monoapi.auth.utils import (
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
