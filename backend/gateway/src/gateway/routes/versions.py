"""Tasarım versiyonları: manuel adlı + otomatik snapshot'lar (customizations).
Otomatik snapshot'lar proje başına son 10 ile sınırlı."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project, Version
from gateway.models.schemas import VersionIn, VersionOut

router = APIRouter(prefix="/projects/{project_id}/versions", dependencies=[require_token()])
_AUTO_CAP = 10


def _proj_or_404(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "Proje bulunamadı")
    return p


@router.post("", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
def create_version(project_id: str, payload: VersionIn, db: Session = Depends(get_db)) -> Version:
    _proj_or_404(db, project_id)
    v = Version(project_id=project_id, name=payload.name, auto=payload.auto,
                customizations=payload.customizations)
    db.add(v); db.commit(); db.refresh(v)
    if payload.auto:
        autos = list(db.scalars(select(Version).where(
            Version.project_id == project_id, Version.auto.is_(True)
        ).order_by(Version.created_at.desc())))
        for old in autos[_AUTO_CAP:]:
            db.delete(old)
        db.commit()
    return v


@router.get("", response_model=list[VersionOut])
def list_versions(project_id: str, db: Session = Depends(get_db)) -> list[Version]:
    return list(db.scalars(select(Version).where(Version.project_id == project_id)
                           .order_by(Version.auto.asc(), Version.created_at.desc())))


@router.post("/{version_id}/restore", response_model=VersionOut)
def restore_version(project_id: str, version_id: str, db: Session = Depends(get_db)) -> Version:
    v = db.get(Version, version_id)
    if v is None or v.project_id != project_id:
        raise HTTPException(404, "Versiyon bulunamadı")
    return v  # frontend customizations'ı store'a yükler


@router.delete("/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(project_id: str, version_id: str, db: Session = Depends(get_db)) -> None:
    v = db.get(Version, version_id)
    if v is None or v.project_id != project_id:
        raise HTTPException(404, "Versiyon bulunamadı")
    db.delete(v); db.commit()
