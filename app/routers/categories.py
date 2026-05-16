from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..dependencies import CR
from ..schemas.category import CategoryCreate, CategoryRead, CategoryUpdate


router = APIRouter(
    prefix="/categories",
    tags=["categories"]
)


@router.post("/", response_model=CategoryRead, status_code=201)
def create_category(category: CategoryCreate, cr: CR):
    return cr.create(category)


@router.get("/{cid}", response_model=CategoryRead, status_code=200)
def get_category(cid: UUID, cr: CR):
    category = cr.read(cid)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.get("/", response_model=list[CategoryRead], status_code=200)
def get_categories(cr: CR):
    return cr.list()


@router.patch("/{cid}", response_model=CategoryRead, status_code=200)
def update_category(cid: UUID, data: CategoryUpdate, cr: CR):
    category = cr.update(cid, data)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.delete("/{cid}", status_code=204)
def delete_category(cid: UUID, cr: CR):
    category = cr.delete(cid)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return {"message": "category deleted successfully"}
