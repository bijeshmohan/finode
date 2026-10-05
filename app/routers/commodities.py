from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Commodities
from ..schemas.commodity import CommodityCreate, CommodityRead


router = APIRouter(
    prefix="/commodities",
    tags=["commodities"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/", response_model=list[CommodityRead])
def list_commodities(commodities: Commodities):
    return commodities.list()


@router.post("/", response_model=CommodityRead, status_code=201)
def create_commodity(data: CommodityCreate, commodities: Commodities):
    try:
        return commodities.create(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{code}", response_model=CommodityRead)
def get_commodity(code: str, commodities: Commodities):
    commodity = commodities.read_by_code(code)
    if commodity is None:
        raise HTTPException(status_code=404, detail="commodity not found")
    return commodity


@router.delete("/{cid}", status_code=204)
def delete_commodity(cid: UUID, commodities: Commodities):
    try:
        commodities.delete(cid)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
