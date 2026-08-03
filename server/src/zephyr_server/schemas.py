from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    name: str
    picture_url: str | None


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expires_at: datetime | None = None


class TokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class TokenCreated(TokenRead):
    token: str


class DeviceAuthorizationCreate(BaseModel):
    device_name: str = Field(min_length=1, max_length=100)


class DeviceAuthorizationCreated(BaseModel):
    device_code: str
    verification_url: str
    expires_in: int
    interval: int


class DeviceTokenExchange(BaseModel):
    device_code: str = Field(min_length=20, max_length=200)


class DeviceTokenResult(BaseModel):
    status: Literal["pending", "approved", "expired", "consumed"]
    token: str | None = None
    email: EmailStr | None = None


class DeviceApprovalRead(BaseModel):
    status: Literal["approved"]
    device_name: str


RunStatus = Literal["starting", "running", "completed", "failed", "interrupted", "unreachable"]


class RunCreate(BaseModel):
    id: uuid.UUID | None = None
    alamo_hash: str | None = Field(default=None, max_length=64)
    name: str = Field(default="Untitled run", max_length=240)
    status: RunStatus = "starting"
    progress: int | None = Field(default=None, ge=0, le=100)
    started_at: datetime | None = None
    host: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=255)
    scheduler_job_id: str | None = Field(default=None, max_length=255)
    git_commit: str | None = Field(default=None, max_length=128)
    git_repository_url: str | None = Field(default=None, max_length=500)
    command: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class RunUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    status: RunStatus | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    tags: list[str] | None = None
    notes: str | None = None


class ArtifactPreview(BaseModel):
    id: uuid.UUID
    logical_name: str
    path: str
    kind: str
    content_type: str
    download_url: str | None = None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    owner_id: uuid.UUID
    alamo_hash: str | None
    name: str
    status: str
    effective_status: str
    progress: int | None
    last_heartbeat: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    host: str | None
    platform: str | None
    scheduler_job_id: str | None
    git_commit: str | None
    git_repository_url: str | None
    command: list[str]
    tags: list[str]
    notes: str
    thumbnail_artifact_id: uuid.UUID | None
    artifact_count: int = 0
    artifact_previews: list[ArtifactPreview] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class Heartbeat(BaseModel):
    sequence: int = Field(ge=0)
    status: RunStatus = "running"
    progress: int | None = Field(default=None, ge=0, le=100)
    observed_at: datetime | None = None


class MetadataWrite(BaseModel):
    raw_text: str = Field(max_length=2_000_000)


class MetadataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    raw_text: str
    values: dict[str, str]
    sections: dict[str, list[str]]
    digest: str


class RunOutputWrite(BaseModel):
    stdout: str | None = Field(default=None, max_length=2_000_000)
    stdout_truncated: bool | None = None
    git_diff: str | None = Field(default=None, max_length=2_000_000)
    git_diff_truncated: bool | None = None


class RunOutputRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    stdout: str
    stdout_truncated: bool
    git_diff: str
    git_diff_truncated: bool
    updated_at: datetime


class ThermoRow(BaseModel):
    sequence: int = Field(ge=0)
    values: dict[str, float | None]


class ThermoBatch(BaseModel):
    segment: int = Field(default=0, ge=0)
    columns: list[str] = Field(min_length=1)
    rows: list[ThermoRow] = Field(max_length=10_000)

    @field_validator("columns")
    @classmethod
    def unique_columns(cls, columns: list[str]) -> list[str]:
        if len(columns) != len(set(columns)):
            raise ValueError("thermo columns must be unique")
        return columns


class ThermoSeriesRead(BaseModel):
    segment: int
    columns: list[str]
    rows: list[ThermoRow]


class ArtifactInitiate(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    content_type: str = Field(default="application/octet-stream", max_length=255)


class ArtifactInitiated(BaseModel):
    already_present: bool
    upload_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class ArtifactComplete(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: str = Field(min_length=1, max_length=2048)
    logical_name: str | None = Field(default=None, max_length=240)
    kind: Literal["file", "table", "image", "log", "input", "checkpoint"] = "file"
    attributes: dict[str, Any] = Field(default_factory=dict)
    derivation: dict[str, Any] = Field(default_factory=dict)


class ArtifactRead(BaseModel):
    id: uuid.UUID
    sha256: str
    size: int
    content_type: str
    logical_name: str
    path: str
    version: int
    kind: str
    attributes: dict[str, Any]
    derivation: dict[str, Any]
    download_url: str | None = None


class ProjectCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,98}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    visibility: Literal["private", "group", "public"] = "private"


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    owner_id: uuid.UUID
    slug: str
    name: str
    description: str
    visibility: str


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    visibility: Literal["private", "group", "public"] | None = None


class ProjectMemberAdd(BaseModel):
    email: EmailStr
    role: Literal["viewer", "editor"] = "viewer"


class ProjectMemberRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    name: str
    role: str


class ProjectRunAdd(BaseModel):
    run_id: uuid.UUID


class PlotRecipeWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    project_id: uuid.UUID | None = None
    config: dict[str, Any]


class ComparisonViewWrite(PlotRecipeWrite):
    pass


class SavedViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
