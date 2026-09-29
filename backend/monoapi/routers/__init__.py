from fastapi import APIRouter, Depends

from monoapi.auth.security import access_token_bearer
from .rest.v1 import v1_routers

__all__ = [
    "api_router",
]

api_router = APIRouter(prefix="/api")  # , dependencies=[Depends(access_token_bearer)]

api_router.include_router(v1_routers)