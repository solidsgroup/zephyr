from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UTCDateTime = DateTime(timezone=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    picture_url: Mapped[str | None] = mapped_column(Text)
    google_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    tokens: Mapped[list[ApiToken]] = relationship(back_populates="user", cascade="all, delete")


class ApiToken(TimestampMixin, Base):
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship(back_populates="tokens")


class DeviceAuthorization(TimestampMixin, Base):
    __tablename__ = "device_authorizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    device_name: Mapped[str] = mapped_column(String(100))
    device_secret_hash: Mapped[str] = mapped_column(String(64))
    browser_secret_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(20), default="private", index=True)


class ProjectMembership(TimestampMixin, Base):
    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), default="viewer")


class Run(TimestampMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("owner_id", "alamo_hash", name="uq_run_owner_hash"),
        Index("ix_runs_owner_updated", "owner_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    alamo_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(240), default="Untitled run")
    status: Mapped[str] = mapped_column(String(30), default="starting", index=True)
    progress: Mapped[int | None] = mapped_column(Integer)
    event_sequence: Mapped[int] = mapped_column(BigInteger, default=-1)
    last_heartbeat: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    host: Mapped[str | None] = mapped_column(String(255))
    platform: Mapped[str | None] = mapped_column(String(255))
    scheduler_job_id: Mapped[str | None] = mapped_column(String(255))
    git_commit: Mapped[str | None] = mapped_column(String(128), index=True)
    command: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")

    metadata_record: Mapped[RunMetadata | None] = relationship(
        back_populates="run", cascade="all, delete", uselist=False
    )
    thermo_series: Mapped[list[ThermoSeries]] = relationship(
        back_populates="run", cascade="all, delete"
    )
    artifacts: Mapped[list[RunArtifact]] = relationship(back_populates="run", cascade="all, delete")


class RunProject(Base):
    __tablename__ = "run_projects"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )


class RunMetadata(TimestampMixin, Base):
    __tablename__ = "run_metadata"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    raw_text: Mapped[str] = mapped_column(Text, default="")
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sections: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    digest: Mapped[str] = mapped_column(String(64), default="")

    run: Mapped[Run] = relationship(back_populates="metadata_record")


class ThermoSeries(TimestampMixin, Base):
    __tablename__ = "thermo_series"
    __table_args__ = (UniqueConstraint("run_id", "segment"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    segment: Mapped[int] = mapped_column(Integer, default=0)
    columns: Mapped[list[str]] = mapped_column(JSON, default=list)

    run: Mapped[Run] = relationship(back_populates="thermo_series")
    points: Mapped[list[ThermoPoint]] = relationship(
        back_populates="series", cascade="all, delete", order_by="ThermoPoint.sequence"
    )


class ThermoPoint(Base):
    __tablename__ = "thermo_points"
    __table_args__ = (UniqueConstraint("series_id", "sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("thermo_series.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(BigInteger)
    values: Mapped[dict[str, float | None]] = mapped_column(JSON)

    series: Mapped[ThermoSeries] = relationship(back_populates="points")


class ArtifactObject(TimestampMixin, Base):
    __tablename__ = "artifact_objects"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class RunArtifact(TimestampMixin, Base):
    __tablename__ = "run_artifacts"
    __table_args__ = (UniqueConstraint("run_id", "path", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    object_sha256: Mapped[str] = mapped_column(ForeignKey("artifact_objects.sha256"))
    logical_name: Mapped[str] = mapped_column(String(240))
    path: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30), default="file")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    derivation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[Run] = relationship(back_populates="artifacts")
    object: Mapped[ArtifactObject] = relationship()


class PlotRecipe(TimestampMixin, Base):
    __tablename__ = "plot_recipes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)


class ComparisonView(TimestampMixin, Base):
    __tablename__ = "comparison_views"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
