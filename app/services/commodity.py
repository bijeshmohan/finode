from uuid import UUID

from ..models.commodity import Commodity
from ..repositories import CommodityRepository
from ..schemas.commodity import CommodityCreate, CommodityRead


class CommodityService:
    def __init__(self, cr: CommodityRepository):
        self.cr = cr

    @staticmethod
    def _to_read(commodity: Commodity) -> CommodityRead:
        return CommodityRead(
            cid=commodity.cid,
            code=commodity.code,
            name=commodity.name,
            kind=commodity.kind,
            decimals=commodity.decimals,
            symbol=commodity.symbol,
        )

    def list(self) -> list[CommodityRead]:
        return [self._to_read(c) for c in self.cr.list()]

    def read_by_code(self, code: str) -> CommodityRead | None:
        commodity = self.cr.read_by_code(code)
        return self._to_read(commodity) if commodity else None

    def create(self, data: CommodityCreate) -> CommodityRead:
        """Add a commodity of the user's own, for anything that is not a built-in currency."""
        if self.cr.read_by_code(data.code):
            raise ValueError(f"'{data.code}' already exists: use that one instead, or pick another code (for example {data.code}.NS)!")
        commodity = self.cr.create(**data.model_dump())
        self.cr.db.commit()
        self.cr.db.refresh(commodity)
        return self._to_read(commodity)

    def delete(self, cid: UUID) -> CommodityRead:
        commodity = self.cr.read(cid)
        if commodity is None:
            raise LookupError("commodity not found")
        if commodity.user is None:
            raise ValueError(f"'{commodity.code}' is a built-in currency and cannot be removed!")
        if self.cr.in_use(cid):
            raise ValueError(f"'{commodity.code}' is in use by accounts, transactions or prices, so it cannot be removed!")
        read = self._to_read(commodity)
        self.cr.delete(cid)
        self.cr.db.commit()
        return read
