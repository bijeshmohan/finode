"""Supabase's own users table (schema `auth`), mapped only so that `user_id` columns can point at it."""

from uuid import UUID

from sqlmodel import Field, SQLModel


class AuthUser(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}

    id: UUID = Field(primary_key=True)
