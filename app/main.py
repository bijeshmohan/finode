from fastapi import FastAPI

from .routers import accounts, transactions


app = FastAPI(title="finode")
app.include_router(accounts.router)
app.include_router(transactions.router)


@app.get("/")
def main():
    return {"message": "welcome to finode"}
