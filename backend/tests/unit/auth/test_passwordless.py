from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from monoapi.auth.routers.api import router
from monoapi.auth.schemas import SignInSchema, TokenInfoSchema
from monoapi.auth.services.auth_service import SignInService, token_repo, user_repo
from monoapi.routers.rest.v1.users.api import router as users_router


@pytest.mark.asyncio
async def test_token_accepts_username_without_password(monkeypatch):
    received = []

    async def call(service):
        received.append(service.request_data.username)
        return TokenInfoSchema(access_token="access-example"), "refresh-example"

    monkeypatch.setattr(SignInService, "__call__", call)
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/token", data={"username": "alice"})
    assert response.status_code == 200
    assert response.json()["access_token"] == "access-example"
    assert received == ["alice"]
    assert "refresh_token=refresh-example" in response.headers["set-cookie"]


@pytest.mark.asyncio
@pytest.mark.parametrize("exists", [True, False])
async def test_signin_looks_up_username(monkeypatch, exists):
    user = SimpleNamespace(is_active=True) if exists else None
    lookup = AsyncMock(return_value=user)
    tokens = AsyncMock(return_value=(TokenInfoSchema(access_token="access-example"), "refresh-example"))
    monkeypatch.setattr(user_repo, "get_user_by_username", lookup)
    monkeypatch.setattr(token_repo, "create_tokens", tokens)
    service = SignInService(request_data=SignInSchema(username="alice"))
    service._session = object()
    if exists:
        assert await service.process() == tokens.return_value
        tokens.assert_awaited_once_with(user, service._session, None)
    else:
        with pytest.raises(HTTPException) as error:
            await service.process()
        assert error.value.status_code == 401
        tokens.assert_not_awaited()
    lookup.assert_awaited_once_with(service._session, "alice")


def test_swagger_uses_http_bearer_without_password_flow():
    app = FastAPI()
    app.include_router(router)
    app.include_router(users_router)
    schemes = app.openapi()["components"]["securitySchemes"]
    assert schemes
    assert all(s["type"] == "http" and s["scheme"] == "bearer" for s in schemes.values())
