from uuid import UUID

from pydantic import BaseModel


class CommodityRead(BaseModel):
    cid: UUID
    code: str
    name: str
    kind: str
    decimals: int
    symbol: str | None = None
    # True for the shared catalog, False for the user's own commodities.
    is_global: bool
