from http.cookies import SimpleCookie
import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient

from monoapi.auth.routers.api import clear_refresh_cookie, router, set_refresh_cookie
from monoapi.auth.services import LogoutService
from monoapi.core import settings


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_logout_clears_same_cookie_as_signin(monkeypatch, protocol):
    monkeypatch.setattr(settings, "api_protocol", protocol)
    signin_response = Response()
    logout_response = Response()

    set_refresh_cookie(signin_response, "example-refresh-token")
    clear_refresh_cookie(logout_response)

    signin = SimpleCookie(signin_response.headers["set-cookie"])["refresh_token"]
    logout = SimpleCookie(logout_response.headers["set-cookie"])["refresh_token"]
    assert logout.value == ""
    assert logout["max-age"] == "0"
    assert logout["path"] == signin["path"] == "/auth"
    assert logout["httponly"] is signin["httponly"] is True
    assert logout["samesite"] == signin["samesite"] == "lax"
    assert bool(logout["secure"]) == bool(signin["secure"]) == (protocol == "https")


@pytest.mark.asyncio
async def test_logout_route_revokes_session_and_returns_empty_204(monkeypatch):
    received = []

    async def call(service):
        received.append(service.refresh_token)

    monkeypatch.setattr(LogoutService, "__call__", call)
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/logout", headers={"Cookie": "refresh_token=refresh-example"})

    assert received == ["refresh-example"]
    assert response.status_code == 204
    assert response.content == b""
    assert "Max-Age=0" in response.headers["set-cookie"]
