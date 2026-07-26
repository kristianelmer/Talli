from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import BaseHTTPMiddleware

API_VERSION = "v1"
CONTRACT_VERSION = "1.0.0"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class TransportModel(BaseModel):
    model_config = ConfigDict(alias_generator=lambda name: _to_camel(name), populate_by_name=True)


class SystemBoundaryStatus(TransportModel):
    api_version: str
    service: str
    status: str


class ProblemDetails(TransportModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str


def _request_id(request: Request) -> str:
    candidate = request.headers.get("X-Request-ID", "")
    return candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = _request_id(request)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


app = FastAPI(
    title="Talli API",
    summary="Talli web-to-backend production boundary",
    version=CONTRACT_VERSION,
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(RequestIdMiddleware)


@app.get(
    "/api/v1/system-boundary/tracer",
    operation_id="systemBoundaryGetTracerStatus",
    response_model=SystemBoundaryStatus,
    responses={
        503: {
            "description": "The backend boundary is temporarily unavailable.",
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
    },
    tags=["system-boundary"],
)
async def get_system_boundary_status() -> SystemBoundaryStatus:
    return SystemBoundaryStatus(
        api_version=API_VERSION,
        service="talli-backend",
        status="AVAILABLE",
    )


@app.get("/health/live", include_in_schema=False)
async def liveness() -> JSONResponse:
    return JSONResponse(
        {"status": "alive"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health/ready", include_in_schema=False)
async def readiness() -> JSONResponse:
    return JSONResponse(
        {"status": "ready"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/openapi.json", include_in_schema=False)
async def served_openapi() -> Response:
    from talli_backend.openapi import serialize_openapi

    return Response(
        content=serialize_openapi(app),
        media_type="application/vnd.oai.openapi+json;version=3.1",
        headers={"Cache-Control": "no-store"},
    )
