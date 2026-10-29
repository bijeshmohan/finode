from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Categories
from ..schemas.account import MergeRequest, MergeResult
from ..schemas.category import CategoryCreate, CategoryDeleteResult, CategoryRead, CategoryUpdate
from ..services.account import SystemAccountError

router = APIRouter(
    prefix="/categories",
    tags=["categories"],
    dependencies=[Depends(require_authenticated_user)],
)


def _refused(e: ValueError) -> HTTPException:
    message = str(e)
    return HTTPException(status_code=404 if "not found" in message else 400, detail=message)


@router.get("/", response_model=list[CategoryRead])
def list_categories(
    categories: Categories, kind: Literal["spending", "earning"] | None = None, include_closed: bool = False
):
    """Your categories (what money was for): spending ones are what the budget plans against, earning ones label
    income. A group has no parent; a category inside it names it as `parent_id`."""
    return categories.list(kind, include_closed)


@router.post("/", response_model=CategoryRead, status_code=201)
def create_category(data: CategoryCreate, categories: Categories):
    """Make a category, or a group (leave out `parent_id`) to put categories in. Two levels at most; names are unique
    inside a group, capitals aside."""
    try:
        return categories.create(data)
    except ValueError as e:
        raise _refused(e) from None


@router.get("/{bcid}", response_model=CategoryRead)
def get_category(bcid: UUID, categories: Categories):
    category = categories.read(bcid)
    if category is None:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.patch("/{bcid}", response_model=CategoryRead)
def update_category(bcid: UUID, data: CategoryUpdate, categories: Categories):
    """Rename a category, change its note or move it into another group (`parent_id`; null takes it out of its group)."""
    try:
        return categories.update(bcid, data)
    except SystemAccountError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise _refused(e) from None


@router.post("/{bcid}/close", response_model=CategoryRead)
def close_category(bcid: UUID, categories: Categories):
    """Close a category (and what is inside a group): its history stays, nothing more can be labelled with it."""
    try:
        return categories.close(bcid)
    except ValueError as e:
        raise _refused(e) from None


@router.post("/{bcid}/reopen", response_model=CategoryRead)
def reopen_category(bcid: UUID, categories: Categories):
    try:
        return categories.reopen(bcid)
    except ValueError as e:
        raise _refused(e) from None


@router.post("/{bcid}/delete", response_model=CategoryDeleteResult)
def delete_category(bcid: UUID, categories: Categories):
    """Remove an unused category for good. One with history (entries, labelled lines, sub-categories or a recurring
    rule) is closed instead, and the answer says which happened."""
    try:
        return categories.delete(bcid)
    except SystemAccountError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise _refused(e) from None


@router.post("/{bcid}/merge", response_model=MergeResult)
def merge_category(bcid: UUID, data: MergeRequest, categories: Categories, dry_run: bool = False):
    """Fold this category into another (`into`, a category id): its entries, labelled lines, planned amounts and
    recurring rules become the other's, and this one goes. Same rules as merging accounts; `dry_run=true` only tells
    what would move."""
    try:
        return categories.merge(bcid, data.into, dry_run)
    except ValueError as e:
        raise _refused(e) from None
