from fastapi import APIRouter, Depends

from ...web_auth import web_login_required
from . import accounts, auth, home, transactions


router = APIRouter(prefix="/app", include_in_schema=False)
router.include_router(auth.router)

protected = APIRouter(dependencies=[Depends(web_login_required)])
protected.include_router(home.router)
protected.include_router(accounts.router)
protected.include_router(transactions.router)
router.include_router(protected)
