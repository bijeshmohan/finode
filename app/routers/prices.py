from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Prices
from ..schemas.price import PriceCreate, PriceRead, RateRead


router = APIRouter(
    prefix="/prices",
    tags=["prices"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/", response_model=list[PriceRead])
def list_prices(prices: Prices, commodity: str | None = None):
    try:
        return prices.list(commodity)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/rate", response_model=RateRead)
def get_rate(prices: Prices, commodity: str, quote: str, on: date | None = None):
    """How many `quote` one `commodity` is worth, from the latest price on or before the day."""
    try:
        return prices.rate(commodity, quote, on or date.today())
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/", response_model=PriceRead, status_code=201)
def set_price(data: PriceCreate, prices: Prices):
    """Set your own price for a day; it replaces the one you already entered for it."""
    try:
        return prices.set(data)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{pid}", status_code=204)
def delete_price(pid: UUID, prices: Prices):
    try:
        prices.delete(pid)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
