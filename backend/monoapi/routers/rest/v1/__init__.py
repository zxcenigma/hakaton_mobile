from fastapi import APIRouter
from .users import router as users_router

v1_routers = APIRouter(prefix="/v1")

v1_routers.include_router(users_router)

