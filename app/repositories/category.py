from uuid import UUID

from sqlmodel import Session, select

from ..models.category import Category
from ..schemas.category import CategoryCreate, CategoryUpdate


def create(db: Session, data: CategoryCreate) -> Category:
    category = Category(**data.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def read(db: Session, cid: UUID) -> Category | None:
    statement = select(Category).where(Category.cid == cid)
    category = db.exec(statement).first()
    return category


def read_all(db: Session) -> list[Category]:
    statement = select(Category)
    categories = db.exec(statement).all()
    return categories


def update(db: Session, cid: UUID, data: CategoryUpdate) -> Category | None:
    category = db.get(Category, cid)
    if not category:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(category, key, value)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def delete(db: Session, cid: UUID) -> Category | None:
    category = db.get(Category, cid)
    if not category:
        return None
    db.delete(category)
    db.commit()
    return category
