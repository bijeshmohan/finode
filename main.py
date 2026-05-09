from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel

from dependencies import engine
from routers import accounts, categories, transactions


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    yield
    ...


app = FastAPI(title="finode", lifespan=lifespan)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(transactions.router)


@app.get("/")
def main():
    return {"message": "welcome to finode"}
