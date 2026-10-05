from fastapi import APIRouter, Depends

from ...web_auth import web_login_required
from . import accounts, auth, commodities, dashboard, data, profile, transactions


router = APIRouter(prefix="/app", include_in_schema=False)
router.include_router(auth.router)

protected = APIRouter(dependencies=[Depends(web_login_required)])
protected.include_router(dashboard.router)
protected.include_router(accounts.router)
protected.include_router(transactions.router)
protected.include_router(profile.router)
protected.include_router(commodities.router)
protected.include_router(data.router)
router.include_router(protected)
