from fastapi import APIRouter

from .diary import router as diary_router
from .targets import router as targets_router
from .users import router as users_router

v1_routers = APIRouter(prefix="/v1")
v1_routers.include_router(users_router)
v1_routers.include_router(diary_router)
v1_routers.include_router(targets_router)
