from fastapi import APIRouter, Depends

from ...dependencies import load_currency
from ...web_auth import web_login_required
from . import accounts, auth, budget, categories, dashboard, data, oauth, profile, recurring, settings, transactions


router = APIRouter(include_in_schema=False)
router.include_router(auth.router)
router.include_router(budget.legacy)

protected = APIRouter(dependencies=[Depends(web_login_required), Depends(load_currency)])
protected.include_router(dashboard.router)
protected.include_router(accounts.router)
protected.include_router(budget.router)
protected.include_router(categories.router)
protected.include_router(recurring.router)
protected.include_router(transactions.router)
protected.include_router(profile.router)
protected.include_router(settings.router)
protected.include_router(data.router)
protected.include_router(oauth.router)
router.include_router(protected)
