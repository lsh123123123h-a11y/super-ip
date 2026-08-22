from contextlib import asynccontextmanager
from time import perf_counter
import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    ai_providers,
    agent,
    assets,
    business,
    health,
    identity,
    metering,
    operations,
    providers,
    workflows,
)
from app.core.auth import AuthenticationError, PrincipalResolver
from app.core.config import get_settings
from app.core.database import SessionLocal, create_schema
from app.core.observability import (
    bind_correlation,
    configure_structured_logging,
    observe_http,
    reset_correlation,
)
from app.models.identity import AuthenticationAuditEvent

settings = get_settings()
configure_structured_logging(settings.log_level)
logger = logging.getLogger("xingliu.api")
principal_resolver = PrincipalResolver(settings)
PUBLIC_PATHS = {"/health", "/health/live", "/health/ready", "/metrics", "/openapi.json", "/docs", "/redoc"}
CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        await create_schema()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def identity_and_observability(request: Request, call_next):
    started = perf_counter()
    supplied_request_id = request.headers.get("X-Request-Id") or ""
    request_id = (
        supplied_request_id
        if CORRELATION_PATTERN.fullmatch(supplied_request_id)
        else str(uuid.uuid4())
    )
    supplied_trace_id = request.headers.get("X-Trace-Id") or ""
    trace_id = (
        supplied_trace_id
        if CORRELATION_PATTERN.fullmatch(supplied_trace_id)
        else request_id
    )
    request.state.request_id = request_id
    request.state.trace_id = trace_id
    token = bind_correlation(request_id=request_id, trace_id=trace_id)
    response = None
    try:
        if request.method != "OPTIONS" and request.url.path not in PUBLIC_PATHS:
            try:
                async with SessionLocal() as session:
                    request.state.principal = await principal_resolver.resolve(request, session)
            except AuthenticationError as exc:
                async with SessionLocal() as session:
                    session.add(
                        AuthenticationAuditEvent(
                            auth_type=settings.auth_mode,
                            outcome="rejected",
                            request_id=request_id,
                            detail=exc.code,
                            metadata_payload={"path": request.url.path},
                        )
                    )
                    await session.commit()
                response = JSONResponse(
                    status_code=401,
                    content={"detail": str(exc), "code": exc.code},
                )
            else:
                principal = request.state.principal
                reset_correlation(token)
                token = bind_correlation(
                    request_id=request_id,
                    trace_id=trace_id,
                    tenant_id=principal.tenant_id,
                )
        if response is None:
            response = await call_next(request)
        route = getattr(request.scope.get("route"), "path", request.url.path)
        observe_http(request.method, route, response.status_code, started)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Trace-Id"] = trace_id
        logger.info(
            "http_request_completed",
            extra={
                "fields": {
                    "method": request.method,
                    "route": route,
                    "status": response.status_code,
                }
            },
        )
        return response
    finally:
        reset_correlation(token)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(agent.router, prefix=settings.api_prefix)
app.include_router(ai_providers.router, prefix=settings.api_prefix)
app.include_router(assets.router, prefix=settings.api_prefix)
app.include_router(business.router, prefix=settings.api_prefix)
app.include_router(identity.router, prefix=settings.api_prefix)
app.include_router(metering.router, prefix=settings.api_prefix)
app.include_router(operations.router, prefix=settings.api_prefix)
app.include_router(providers.router, prefix=settings.api_prefix)
app.include_router(workflows.router, prefix=settings.api_prefix)
