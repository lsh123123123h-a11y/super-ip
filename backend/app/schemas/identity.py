from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MemberRead(BaseModel):
    user_id: str
    display_name: str
    external_subject: str
    role: str
    status: str
    created_at: datetime


class MemberRoleUpdate(BaseModel):
    role: str = Field(pattern="^(owner|admin|member|viewer)$")


class RoleRead(BaseModel):
    key: str
    name: str
    permissions: list[str]


class ServicePrincipalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    permissions: list[str] = Field(default_factory=list)


class ServicePrincipalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    name: str
    permissions: list[str]
    status: str
    created_at: datetime
    last_authenticated_at: datetime | None
    revoked_at: datetime | None
    initial_secret: str | None = None
