from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from schemas.category import CategoryCreate, CategoryRead, CategoryUpdate


router = APIRouter(
    prefix="/categories",
    tags=["categories"]
)

CATEGORIES = []


@router.post("/", status_code=201)
def create_category(category: CategoryCreate):
    cid = uuid4()
    CATEGORIES.append({"cid": cid, **category.dict()})
    return {
        "message": "category created successfully",
        "category": {"cid": cid, **category.dict()}
    }


@router.get("/{cid}", response_model=CategoryRead, status_code=200)
def get_category(cid: UUID):
    category = next((cat for cat in CATEGORIES if cat["cid"] == cid), None)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    return category


@router.get("/", response_model=list[CategoryRead], status_code=200)
def get_categories():
    return CATEGORIES


@router.patch("/{cid}", response_model=CategoryRead, status_code=200)
def update_category(cid: UUID, update: CategoryUpdate):
    current = next((cat for cat in CATEGORIES if cat["cid"] == cid), None)
    if not current:
        raise HTTPException(status_code=404, detail="category not found")
    CATEGORIES.remove(current)
    updated = {"cid": cid, **update.dict()}
    CATEGORIES.append(updated)
    return updated


@router.delete("/{cid}", status_code=204)
def delete_category(cid: UUID):
    category = next((cat for cat in CATEGORIES if cat["cid"] == cid), None)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    CATEGORIES.remove(category)
    return {"message": "category deleted successfully"}
