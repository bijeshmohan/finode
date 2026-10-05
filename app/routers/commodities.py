from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Commodities
from ..schemas.commodity import CommodityRead


router = APIRouter(
    prefix="/commodities",
    tags=["commodities"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/", response_model=list[CommodityRead])
def list_commodities(commodities: Commodities):
    return commodities.list()


@router.get("/{code}", response_model=CommodityRead)
def get_commodity(code: str, commodities: Commodities):
    commodity = commodities.read_by_code(code)
    if commodity is None:
        raise HTTPException(status_code=404, detail="commodity not found")
    return commodity
