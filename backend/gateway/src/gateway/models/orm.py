"""SQLAlchemy 2.0 ORM modelleri.

Faz 1: tek tablo (projects), tek kullanıcı (user_id='default').
Faz 9'da users tablosu + FK eklenecek; user_id alanı şimdiden var.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    user_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    name: Mapped[str] = mapped_column(String(200), default="İsimsiz Tasarım")
    garment_type: Mapped[str] = mapped_column(String(32))
    template_id: Mapped[str] = mapped_column(String(64))
    customizations: Mapped[dict] = mapped_column(JSON, default=dict)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    mesh_path: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    engine_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)  # hangi motor üretti
    animation_path: Mapped[str | None] = mapped_column(String, nullable=True, default=None)  # VideoMDM animation.mp4 yolu
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Variation(Base):
    __tablename__ = "variations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # "motif" | "style" (gelecek: "text_3d")
    seed: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="SUBMITTED")  # SUBMITTED|SUCCESS|FAILURE
    result_path: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)  # proje-göreli
    thumbnail_path: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    variation_id: Mapped[str] = mapped_column(String(32), index=True, unique=True)
    marked_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Version(Base):
    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    customizations: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
