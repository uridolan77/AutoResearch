from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.core.db import get_db
from app.folders import ingest_folder, suggest_targets
from app.models import Folder

router = APIRouter(prefix="/folders", tags=["folders"])


@router.post(
    "/ingest",
    status_code=status.HTTP_201_CREATED,
)
def ingest(body: dict, db: DbSession = Depends(get_db)) -> dict:
    path_or_url = (body.get("path_or_url") or "").strip()
    if not path_or_url:
        raise HTTPException(status_code=422, detail="path_or_url is required")
    try:
        folder_path, is_git_clone, original = ingest_folder(path_or_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    row = Folder(original=original, folder_path=folder_path, is_git_clone=is_git_clone)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "folder_id": row.id,
        "folder_path": row.folder_path,
        "is_git_clone": row.is_git_clone,
        "original": row.original,
    }


@router.get("/{folder_id}/targets")
def targets(folder_id: str, db: DbSession = Depends(get_db)) -> dict:
    row = db.get(Folder, folder_id)
    if row is None:
        raise HTTPException(status_code=404, detail="folder not found")
    return {"folder_id": row.id, "targets": suggest_targets(row.folder_path)}

