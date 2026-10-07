from typing import Literal

from fastapi import APIRouter, File, Request, UploadFile

from ...dependencies import Data
from ...schemas.data import ImportSummary
from ...services.data import ImportRejected
from ...templating import templates
from ..data import export_response, read_upload
from .utils import htmx_redirect


router = APIRouter()


@router.get("/export")
def export(data: Data, format: Literal["ledger", "csv"] = "ledger"):
    return export_response(data, format)


def _preview(request: Request, summary: ImportSummary, can_confirm: bool = True):
    return templates.TemplateResponse(
        request, "partials/import_preview.html", {"summary": summary, "can_confirm": can_confirm}
    )


@router.post("/import/preview")
def import_preview(request: Request, data: Data, file: UploadFile | None = File(default=None)):
    try:
        summary = data.preview_import(read_upload(file))
    except ValueError as e:
        summary = ImportSummary(errors=[str(e)])
    return _preview(request, summary)


@router.post("/import")
def import_confirm(request: Request, data: Data, file: UploadFile | None = File(default=None)):
    try:
        data.run_import(read_upload(file))
    except ImportRejected as e:
        return _preview(request, e.summary)
    except ValueError as e:
        return _preview(request, ImportSummary(errors=[str(e)]))
    return htmx_redirect("/", flash="import-done")
