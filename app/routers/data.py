import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from ..auth import require_authenticated_user
from ..config import settings
from ..limits import upload_limit_bytes
from ..dependencies import Backup, Data
from ..schemas.backup import RestoreSummary
from ..schemas.data import ImportSummary
from ..services.data import ImportRejected
from ..clock import local_today


MAX_IMPORT_BYTES = 5 * 1024 * 1024

router = APIRouter(tags=["data"], dependencies=[Depends(require_authenticated_user)])


def export_response(data, kind: str) -> Response:
    """The user's data as a downloadable file (`kind` is "ledger" or "csv")."""
    stamp = local_today().isoformat()
    if kind == "csv":
        # A BOM makes Excel read the file as UTF-8.
        body, media, ext = data.export_csv().encode("utf-8-sig"), "text/csv; charset=utf-8", "csv"
    else:
        body, media, ext = data.export_ledger().encode("utf-8"), "text/plain; charset=utf-8", "ledger"
    return Response(
        body, media_type=media, headers={"Content-Disposition": f'attachment; filename="finode-{stamp}.{ext}"'}
    )


def read_upload(file: UploadFile | None, limit: int = MAX_IMPORT_BYTES) -> str:
    """The uploaded journal as text; raises ValueError with a user-facing reason."""
    if file is None or not file.filename:
        raise ValueError("Choose a file first.")
    raw = file.file.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"The file is larger than {limit // (1024 * 1024)} MB.")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("The file is not UTF-8 text.")


@router.get("/export")
def export(data: Data, format: Literal["ledger", "csv"] = "ledger"):
    return export_response(data, format)


@router.post("/import", response_model=ImportSummary)
def import_data(data: Data, file: UploadFile | None = File(default=None), dry_run: bool = False):
    try:
        text = read_upload(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if dry_run:
        return data.preview_import(text)
    try:
        return data.run_import(text)
    except ImportRejected as e:
        raise HTTPException(status_code=400, detail=e.summary.model_dump(mode="json"))


def backup_response(backup) -> Response:
    """Everything the user recorded as one JSON file (see services/backup.py)."""
    body = json.dumps(backup.export(), indent=1, ensure_ascii=False).encode("utf-8")
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="finode-backup-{local_today().isoformat()}.json"'},
    )


def read_backup(file: UploadFile | None) -> dict:
    try:
        data = json.loads(read_upload(file, upload_limit_bytes(settings.max_restore_mb)))
    except json.JSONDecodeError:
        raise ValueError("The file is not a finode backup (it is not valid JSON).")
    if not isinstance(data, dict):
        raise ValueError("The file is not a finode backup.")
    return data


@router.get("/backup")
def backup(backup: Backup):
    """A complete backup: settings, accounts, transactions, recurring rules and the budget."""
    return backup_response(backup)


@router.post("/restore", response_model=RestoreSummary)
def restore(backup: Backup, file: UploadFile | None = File(default=None), dry_run: bool = False):
    """Restore a backup into an empty ledger, all or nothing (`dry_run` shows what would happen)."""
    try:
        summary = backup.restore(read_backup(file), dry_run=dry_run)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if summary.errors:
        raise HTTPException(status_code=400, detail=summary.model_dump(mode="json"))
    return summary
