from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routers import accounts, data, profile, reports, transactions, web
from .caching import cache_headers_middleware
from .flash import clear_shown_flash_middleware
from .templating import BASE_DIR
from .web_auth import LoginRequired, login_required_handler, refreshed_cookies_middleware


app = FastAPI(title="finode")
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(data.router)
app.include_router(profile.router)
app.include_router(reports.router)
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.add_exception_handler(LoginRequired, login_required_handler)
app.middleware("http")(refreshed_cookies_middleware)
app.middleware("http")(clear_shown_flash_middleware)
app.middleware("http")(cache_headers_middleware)


@app.get("/")
def main():
    return {"message": "welcome to finode"}
