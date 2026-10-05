from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...dependencies import Accounts, Commodities, Prices
from ...models.commodity import CommodityKind
from ...schemas.commodity import CommodityCreate
from ...schemas.price import PriceCreate
from ...templating import templates
from .utils import htmx_error, htmx_redirect, parse_amount, validation_message


router = APIRouter(prefix="/commodities")

KIND_LABELS = {
    CommodityKind.CRYPTO: "Crypto",
    CommodityKind.STOCK: "Stock",
    CommodityKind.FUND: "Fund",
    CommodityKind.OTHER: "Other",
}


@router.get("")
def commodities_page(request: Request, accounts: Accounts, commodities: Commodities, prices: Prices):
    default = accounts.default_currency()
    today = date.today()
    listed = commodities.list()
    held = sorted(
        {a.commodity for a in accounts.list() if a.parent_id is not None and a.commodity and a.commodity != default.code}
    )
    rates = [prices.rate(code, default.code, today) for code in held]
    return templates.TemplateResponse(
        request,
        "commodities.html",
        {
            "active": "profile",
            "currency": default.code,
            "rates": rates,
            "prices": prices.list(),
            "mine": [c for c in listed if c.kind != CommodityKind.CURRENCY],
            "currencies": [c for c in listed if c.kind == CommodityKind.CURRENCY],
            "kinds": KIND_LABELS,
            "today": today.isoformat(),
        },
    )


@router.post("")
def add_commodity(
    commodities: Commodities,
    code: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = CommodityKind.STOCK,
    decimals: Annotated[str, Form()] = "2",
    symbol: Annotated[str, Form()] = "",
):
    try:
        try:
            places = int(decimals.strip() or "2")
        except ValueError:
            raise ValueError(f"'{decimals}' is not a whole number of decimal places!")
        commodities.create(CommodityCreate(code=code, name=name, kind=kind, decimals=places, symbol=symbol))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#commodity-error")
    except ValueError as e:
        return htmx_error(str(e), "#commodity-error")
    return htmx_redirect("/app/commodities#mine", flash="commodity-added")


@router.post("/{cid}/delete")
def delete_commodity(cid: UUID, commodities: Commodities):
    try:
        commodities.delete(cid)
    except LookupError:
        raise HTTPException(status_code=404, detail="commodity not found")
    except ValueError as e:
        return htmx_error(str(e), "#mine-error")
    return htmx_redirect("/app/commodities#mine", flash="commodity-deleted")


@router.post("/prices")
def set_price(
    prices: Prices,
    commodity: Annotated[str, Form()] = "",
    quote: Annotated[str, Form()] = "",
    date_: Annotated[str, Form(alias="date")] = "",
    price: Annotated[str, Form()] = "",
):
    try:
        on = date.fromisoformat(date_.strip()) if date_.strip() else date.today()
        prices.set(PriceCreate(commodity=commodity, quote=quote, date=on, price=parse_amount(price)))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#price-error")
    except LookupError as e:
        return htmx_error(str(e).strip("'\""), "#price-error")
    except ValueError as e:
        return htmx_error(str(e), "#price-error")
    return htmx_redirect("/app/commodities#prices", flash="price-saved")


@router.post("/prices/{pid}/delete")
def delete_price(pid: UUID, prices: Prices):
    try:
        prices.delete(pid)
    except LookupError:
        raise HTTPException(status_code=404, detail="price not found")
    return htmx_redirect("/app/commodities#prices", flash="price-deleted")
