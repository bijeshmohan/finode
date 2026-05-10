from uuid import UUID

from fastapi import APIRouter, HTTPException

from dependencies import DBSession
from schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from repositories.category import create, read, read_all, update, delete


router = APIRouter(
    prefix="/categories",
    tags=["categories"]
)


@router.post("/", response_model=CategoryRead, status_code=201)
def create_category(category: CategoryCreate, db: DBSession):
    return create(db, category)


@router.get("/{cid}", response_model=CategoryRead, status_code=200)
def get_category(cid: UUID, db: DBSession):
    category = read(db, cid)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.get("/", response_model=list[CategoryRead], status_code=200)
def get_categories(db: DBSession):
    return read_all(db)


@router.patch("/{cid}", response_model=CategoryRead, status_code=200)
def update_category(cid: UUID, data: CategoryUpdate, db: DBSession):
    category = update(db, cid, data)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.delete("/{cid}", status_code=204)
def delete_category(cid: UUID, db: DBSession):
    category = delete(db, cid)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return {"message": "category deleted successfully"}
