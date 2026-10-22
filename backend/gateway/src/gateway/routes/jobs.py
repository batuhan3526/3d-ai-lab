"""GET /jobs/{id} — WS bağlanamazsa polling fallback."""
from common.jobs import JobStore
from fastapi import APIRouter, HTTPException, status

from gateway.auth import require_token
from gateway.models.schemas import JobListItem, JobOut

router = APIRouter(prefix="/jobs", dependencies=[require_token()])

_STATE_ORDER = {"STARTED": 0, "PROGRESS": 0, "SUBMITTED": 1, "SUCCESS": 2, "FAILURE": 2}


def _job_store() -> JobStore:
    return JobStore()


@router.get("", response_model=list[JobListItem])
def list_jobs() -> list[JobListItem]:
    """Tüm üretim işleri (iş kuyruğu paneli): çalışanlar önce, bitenler sonra."""
    items = [
        JobListItem(
            job_id=d["job_id"], state=d.get("state", "SUBMITTED"), kind=d.get("kind"),
            stage=d.get("stage"), percent=int(d["percent"]) if d.get("percent") else None,
            project_id=d.get("project_id"),
        )
        for d in _job_store().list_jobs()
    ]
    items.sort(key=lambda j: _STATE_ORDER.get(j.state, 3))
    return items


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    data = _job_store().get(job_id)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job yok")
    return JobOut(
        state=data.get("state", "SUBMITTED"),
        stage=data.get("stage"),
        percent=int(data["percent"]) if data.get("percent") else None,
        project_id=data.get("project_id"),
        error=data.get("error"),
        decal_path=data.get("decal_path"),
    )
