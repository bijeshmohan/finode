import re
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from ..models.commodity import CommodityKind


CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}$")


class CommodityRead(BaseModel):
    cid: UUID
    code: str
    name: str
    kind: str
    decimals: int
    symbol: str | None = None
    # True for the shared catalog, False for the user's own commodities.
    is_global: bool


class CommodityCreate(BaseModel):
    code: str = Field(max_length=20)
    name: str = Field(min_length=1, max_length=80)
    kind: str = CommodityKind.STOCK
    decimals: int = Field(default=2, ge=0, le=8)
    symbol: str | None = Field(default=None, max_length=8)

    @field_validator("code")
    @classmethod
    def code_must_be_a_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not CODE_PATTERN.match(v):
            raise ValueError("code must be letters, digits, '.', '_' or '-' (for example INFY or HDFC.BO)!")
        return v

    @field_validator("name")
    @classmethod
    def name_is_trimmed(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty!")
        return v

    @field_validator("kind")
    @classmethod
    def kind_must_be_known(cls, v: str) -> str:
        if v not in CommodityKind.ALL:
            raise ValueError(f"kind must be one of {', '.join(CommodityKind.ALL)}!")
        return v

    @field_validator("symbol")
    @classmethod
    def blank_symbol_is_unset(cls, v: str | None) -> str | None:
        return (v or "").strip() or None
