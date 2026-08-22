from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine_options = {"pool_pre_ping": True}
if os.getenv("TEST_DATABASE_URL"):
    engine_options["poolclass"] = NullPool
engine = create_async_engine(settings.database_url, **engine_options)
SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    info={"system_context": True},
)


@event.listens_for(Session, "after_begin")
def _set_postgres_tenant_context(session: Session, transaction, connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    tenant_id = str(session.info.get("tenant_id") or "")
    system_context = "on" if session.info.get("system_context") else "off"
    connection.execute(
        text(
            "SELECT set_config('app.tenant_id', :tenant_id, true), "
            "set_config('app.system_context', :system_context, true)"
        ),
        {"tenant_id": tenant_id, "system_context": system_context},
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    principal = getattr(request.state, "principal", None)
    tenant_id = getattr(principal, "tenant_id", "")
    async with SessionLocal(
        info={"system_context": False, "tenant_id": tenant_id}
    ) as session:
        yield session


async def get_system_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncIterator[AsyncSession]:
    async with SessionLocal(
        info={"system_context": False, "tenant_id": tenant_id}
    ) as session:
        yield session


async def create_schema() -> None:
    from app import models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
