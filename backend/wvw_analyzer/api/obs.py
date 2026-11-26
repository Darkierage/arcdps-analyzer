"""OBS connection routes: status, the Settings test, and the leftover-recording notice."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..obs import check_connection

if TYPE_CHECKING:
    from ..state import AppState


class ObsTest(BaseModel):
    port: int | None = Field(None, ge=1, le=65535)
    password: str | None = None  # None: the stored one


class Leftover(BaseModel):
    action: Literal["stop", "keep"]


def router(state: AppState) -> APIRouter:
    r = APIRouter()

    @r.get("/api/obs/status")
    def obs_status() -> dict[str, Any]:
        return state.obs.status()

    @r.post("/api/obs/test")
    async def obs_test(body: ObsTest) -> dict[str, Any]:
        s = state.config.settings.obs
        port = body.port or s.port
        password = s.password if body.password is None else body.password
        return await run_in_threadpool(check_connection, port, password)

    @r.post("/api/obs/leftover")
    def obs_leftover(body: Leftover) -> dict[str, Any]:
        return state.obs.leftover(body.action)

    return r
