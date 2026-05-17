from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Categories
from ..schemas.category import CategoryCreate, CategoryRead, CategoryUpdate


router = APIRouter(
    prefix="/categories",
    tags=["categories"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.post("/", response_model=CategoryRead, status_code=201)
def create_category(category: CategoryCreate, categories: Categories):
    return categories.create(category)


@router.get("/{cid}", response_model=CategoryRead, status_code=200)
def get_category(cid: UUID, categories: Categories):
    category = categories.read(cid)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.get("/", response_model=list[CategoryRead], status_code=200)
def get_categories(categories: Categories):
    return categories.list()


@router.patch("/{cid}", response_model=CategoryRead, status_code=200)
def update_category(cid: UUID, data: CategoryUpdate, categories: Categories):
    category = categories.update(cid, data)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.delete("/{cid}", status_code=204)
def delete_category(cid: UUID, categories: Categories):
    category = categories.delete(cid)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return {"message": "category deleted successfully"}
