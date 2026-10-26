"""Looking after the person's tags: the list (Settings › Your data › Tags) and, per tag, Rename, Merge and Delete."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...dependencies import Transactions
from ...tags import clean_name
from ...templating import templates
from .utils import htmx_error, htmx_redirect

router = APIRouter(prefix="/tags")


def _known(transactions: Transactions, name: str):
    """The tag called `name` with its uses and last day, or a 404."""
    try:
        wanted = clean_name(name)
    except ValueError:
        raise HTTPException(status_code=404, detail="tag not found") from None
    tag = next((t for t in transactions.tags() if t.tag == wanted), None)
    if tag is None:
        raise HTTPException(status_code=404, detail="tag not found")
    return tag


@router.get("")
def tags_page(request: Request, transactions: Transactions):
    return templates.TemplateResponse(request, "tags.html", {"active": "settings", "tags": transactions.tags()})


@router.get("/{name}/sheet")
def tag_sheet(request: Request, name: str, transactions: Transactions):
    tag = _known(transactions, name)
    others = [t.tag for t in transactions.tags() if t.tag != tag.tag]
    return templates.TemplateResponse(request, "partials/tag_sheet.html", {"tag": tag, "others": others})


@router.post("/{name}/rename")
def rename_tag(name: str, transactions: Transactions, to: Annotated[str, Form()] = ""):
    tag = _known(transactions, name)
    try:
        transactions.rename_tag(tag.tag, to)
    except (ValueError, ValidationError) as e:
        return htmx_error(str(e), "#tag-sheet-error")
    return htmx_redirect("/tags", flash="tag-renamed")


@router.post("/{name}/merge")
def merge_tag(name: str, transactions: Transactions, into: Annotated[str, Form()] = ""):
    tag = _known(transactions, name)
    try:
        transactions.merge_tags(tag.tag, into)
    except (ValueError, LookupError) as e:
        return htmx_error(str(e), "#tag-sheet-error")
    return htmx_redirect("/tags", flash="tag-merged")


@router.post("/{name}/delete")
def delete_tag(name: str, transactions: Transactions):
    tag = _known(transactions, name)
    transactions.delete_tag(tag.tag)
    return htmx_redirect("/tags", flash="tag-deleted")
