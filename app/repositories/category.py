from uuid import UUID

from sqlmodel import Session, select

from ..models.category import Category
from ..schemas.category import CategoryCreate, CategoryUpdate


class CategoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: CategoryCreate) -> Category:
        category = Category(**data.model_dump())
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def read(self, cid: UUID) -> Category | None:
        statement = select(Category).where(Category.cid == cid)
        category = self.db.exec(statement).first()
        return category

    def list(self) -> list[Category]:
        statement = select(Category)
        categories = self.db.exec(statement).all()
        return categories

    def update(self, cid: UUID, data: CategoryUpdate) -> Category | None:
        category = self.db.get(Category, cid)
        if not category:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(category, key, value)
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def delete(self, cid: UUID) -> Category | None:
        category = self.db.get(Category, cid)
        if not category:
            return None
        self.db.delete(category)
        self.db.commit()
        return category
