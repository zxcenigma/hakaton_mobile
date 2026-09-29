from uuid import UUID

from fastapi import APIRouter, Response

from monoapi.helpers.pydantic import BaseModel
from monoapi.routers.services.targets.get_target import (
    GetTargetService,
    RequestGetTarget,
    ResponseGetTarget,
)
from monoapi.routers.services.targets.create_target import (
    CreateTargetService,
    RequestCreateTarget,
    ResponseCreateTarget,
)
from monoapi.routers.services.targets.edit_target import (
    EditTargetService,
    RequestEditTarget,
    ResponseEditTarget,
)
from monoapi.routers.services.targets.delete_target import (
    DeleteTargetService,
    RequestDeleteTarget,
)


class TargetErrorResponse(BaseModel):
    detail: str | list[dict]


router = APIRouter(
    prefix="/targets",
    tags=["targets"],
    responses={
        404: {
            "model": TargetErrorResponse, 
            "description": "Пользователь или цель не найдены"
        },
        422: {
            "model": TargetErrorResponse, 
            "description": "Ошибка валидации параметров цели"
        },
    },
)


@router.post(
    "", 
    response_model=ResponseCreateTarget, 
    status_code=201
)
async def create_target(
    user_uuid: UUID, 
    request: RequestCreateTarget) -> ResponseCreateTarget:
    
    service = CreateTargetService(
        user_uuid=user_uuid, 
        request_data=request
    )
    return await service()


@router.patch(
    "/{target_uuid}", 
    response_model=ResponseEditTarget, 
    status_code=200
)
async def edit_target(
    user_uuid: UUID, 
    request: RequestEditTarget, 
    target_uuid: UUID) -> ResponseEditTarget:
    
    service = EditTargetService(
        user_uuid=user_uuid, 
        request_data=request, 
        target_uuid=target_uuid
    )
    return await service()


@router.get(
    "/{target_uuid}", 
    response_model=ResponseGetTarget
)
async def get_target(
    user_uuid: UUID, 
    target_uuid: UUID) -> ResponseGetTarget:
    
    service = GetTargetService(user_uuid=user_uuid, request_data=RequestGetTarget(target_uuid=target_uuid))
    return await service()


@router.delete(
    "/{target_uuid}", 
    status_code=204, 
    response_class=Response
)
async def delete_target(
    user_uuid: UUID, 
    target_uuid: UUID) -> Response:
    
    service = DeleteTargetService(user_uuid=user_uuid, request_data=RequestDeleteTarget(target_uuid=target_uuid))
    await service()
    return Response(status_code=204)

