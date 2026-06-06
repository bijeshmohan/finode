from fastapi import FastAPI

from .routers import accounts, journal_entries


app = FastAPI(title="finode")
app.include_router(accounts.router)
app.include_router(journal_entries.router)


@app.get("/")
def main():
    return {"message": "welcome to finode"}
