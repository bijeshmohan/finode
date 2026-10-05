from ..models.commodity import Commodity
from ..repositories import CommodityRepository
from ..schemas.commodity import CommodityRead


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
            is_global=commodity.user is None,
        )

    def list(self) -> list[CommodityRead]:
        return [self._to_read(c) for c in self.cr.list()]

    def read_by_code(self, code: str) -> CommodityRead | None:
        commodity = self.cr.read_by_code(code)
        return self._to_read(commodity) if commodity else None
