"""JSON API for a person's data: export, import, backup, restore, Erase and Delete my account. The web pages reuse its
file helpers and `confirmed`."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from ..auth import CookieSession, CurrentUser, require_authenticated_user, require_cookie_session
from ..clock import local_today
from ..config import settings
from ..dependencies import Backup, Data, Erase
from ..limits import upload_limit_bytes
from ..schemas.backup import RestoreSummary
from ..schemas.data import Confirmation, DataOptions, ImportSummary
from ..services.backup import BackupService
from ..services.data import DataService, ImportRejected
from ..session import AuthUnavailableError, clear_auth_cookies
from ..signup import delete_user

MAX_IMPORT_BYTES = 5 * 1024 * 1024

router = APIRouter(tags=["data"], dependencies=[Depends(require_authenticated_user)])


def export_response(data: DataService, kind: str) -> Response:
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
        raise ValueError("The file is not UTF-8 text.") from None


@router.get("/export")
def export(data: Data, format: Literal["ledger", "csv"] = "ledger"):
    return export_response(data, format)


@router.post("/import", response_model=ImportSummary)
def import_data(data: Data, file: UploadFile | None = File(default=None), dry_run: bool = False):
    try:
        text = read_upload(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if dry_run:
        return data.preview_import(text)
    try:
        return data.run_import(text)
    except ImportRejected as e:
        raise HTTPException(status_code=400, detail=e.summary.model_dump(mode="json")) from None


def backup_response(backup: BackupService) -> Response:
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
        raise ValueError("The file is not a finode backup (it is not valid JSON).") from None
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
        raise HTTPException(status_code=400, detail=str(e)) from None
    if summary.errors:
        raise HTTPException(status_code=400, detail=summary.model_dump(mode="json"))
    return summary


def confirmed(user: CurrentUser, typed: str) -> bool:
    """The person types their email (or DELETE when the account has none) so a stray tap can't erase anything."""
    expected = (user.email or "DELETE").strip().lower()
    return typed.strip().lower() == expected


def _type_to_confirm(user: CurrentUser) -> HTTPException:
    return HTTPException(status_code=400, detail=f"Type {user.email or 'DELETE'} to confirm.")


@router.get("/data-options", response_model=DataOptions)
def data_options(data: Data, backup: Backup, cookie: CookieSession = Depends(require_cookie_session)):
    """What the data page offers: import and restore need empty books; the word Erase and Delete ask you to type."""
    return DataOptions(
        can_import=data.can_import(),
        can_restore=backup.can_restore(),
        confirm_word=cookie.user.email or "DELETE",
        can_delete_login=settings.can_delete_logins,
    )


@router.post("/erase", status_code=204)
def erase_books(data: Confirmation, erase: Erase, cookie: CookieSession = Depends(require_cookie_session)):
    """Erase my books: every entry, account, category, person, rule and budget; the profile and sign-in stay."""
    if not confirmed(cookie.user, data.confirm):
        raise _type_to_confirm(cookie.user)
    erase.erase_books()


@router.post("/delete-account", status_code=204)
def delete_account(
    data: Confirmation, erase: Erase, response: Response, cookie: CookieSession = Depends(require_cookie_session)
):
    """Delete my account: everything, then the sign-in itself (needs Supabase's admin key on the server)."""
    if not confirmed(cookie.user, data.confirm):
        raise _type_to_confirm(cookie.user)
    if not settings.can_delete_logins:
        raise HTTPException(
            status_code=503, detail="Deleting your login is not set up here: ask the person who runs finode."
        )
    erase.erase_everything()
    try:
        delete_user(cookie.user.id)
    except AuthUnavailableError:
        # The books are gone; the sign-in is not. Say so, and let them (or the admin) finish it.
        raise HTTPException(
            status_code=503,
            detail="Your data was erased, but removing your login failed. Try again, or ask the person who runs finode.",
        ) from None
    clear_auth_cookies(response)
