from uuid import UUID

from ..models.category import Category
from ..repositories.category import CategoryRepository
from ..schemas.category import CategoryCreate, CategoryUpdate


class CategoryService:
    def __init__(self, cr: CategoryRepository):
        self.cr = cr

    def create(self, category: CategoryCreate) -> Category:
        return self.cr.create(category)

    def read(self, cid: UUID) -> Category | None:
        return self.cr.read(cid)

    def list(self) -> list[Category]:
        return self.cr.list()

    def update(self, cid: UUID, data: CategoryUpdate) -> Category | None:
        return self.cr.update(cid, data)

    def delete(self, cid: UUID) -> Category | None:
        return self.cr.delete(cid)
