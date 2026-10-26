from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import require_authenticated_user
from ..dependencies import Transactions
from ..limits import LimitReached
from ..schemas.transaction import TagRead
from ..tags import clean_name

router = APIRouter(prefix="/tags", tags=["tags"], dependencies=[Depends(require_authenticated_user)])


class TagRename(BaseModel):
    # The new name (a # and capitals are fine). When it is another of your tags, the two become one.
    name: str


def _find(transactions: Transactions, name: str) -> TagRead | None:
    try:
        wanted = clean_name(name)
    except ValueError:
        return None
    return next((t for t in transactions.tags() if t.tag == wanted), None)


@router.get("/", response_model=list[TagRead])
def list_tags(transactions: Transactions):
    """Your tags, the most used first, each with how many entries carry it and the day of the latest."""
    return transactions.tags()


@router.patch("/{name}", response_model=TagRead)
def rename_tag(name: str, data: TagRename, transactions: Transactions):
    """Rename a tag; when the new name is another of your tags the two become one (a merge)."""
    tag = _find(transactions, name)
    if tag is None:
        raise HTTPException(status_code=404, detail="tag not found")
    try:
        transactions.rename_tag(tag.tag, data.name)
    except (ValueError, LimitReached) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    result = _find(transactions, data.name)
    if result is None:
        raise HTTPException(status_code=404, detail="tag not found")
    return result


@router.delete("/{name}", status_code=204)
def delete_tag(name: str, transactions: Transactions):
    """Take a tag off every entry and remove it. The entries stay as they are."""
    tag = _find(transactions, name)
    if tag is None:
        raise HTTPException(status_code=404, detail="tag not found")
    transactions.delete_tag(tag.tag)
