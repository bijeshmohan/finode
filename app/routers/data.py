from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from ..auth import require_authenticated_user
from ..dependencies import Data
from ..schemas.data import ImportSummary
from ..services.data import ImportRejected


MAX_IMPORT_BYTES = 5 * 1024 * 1024

router = APIRouter(tags=["data"], dependencies=[Depends(require_authenticated_user)])


def export_response(data, kind: str) -> Response:
    """The user's data as a downloadable file (`kind` is "ledger" or "csv")."""
    stamp = date.today().isoformat()
    if kind == "csv":
        # A BOM makes Excel read the file as UTF-8.
        body, media, ext = data.export_csv().encode("utf-8-sig"), "text/csv; charset=utf-8", "csv"
    else:
        body, media, ext = data.export_ledger().encode("utf-8"), "text/plain; charset=utf-8", "ledger"
    return Response(
        body, media_type=media, headers={"Content-Disposition": f'attachment; filename="finode-{stamp}.{ext}"'}
    )


def read_upload(file: UploadFile | None) -> str:
    """The uploaded journal as text; raises ValueError with a user-facing reason."""
    if file is None or not file.filename:
        raise ValueError("Choose a file first.")
    raw = file.file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("The file is larger than 5 MB.")
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
