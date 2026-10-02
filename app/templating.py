from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).parent


def money(value: Decimal | str | None) -> str:
    if value is None:
        return ""
    return format(Decimal(value), ",.2f")


templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["money"] = money
