"""Records due recurring transactions in the background, for every user, even if nobody opens the app.

Each web worker runs this loop. That is safe: an occurrence is only ever recorded once (a unique
index on the rule and its date), and people who open the app also trigger their own catch-up.
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import date

import anyio.to_thread

from .clock import local_today
from .config import settings
from .mcp_server import context
from .repositories import AccountRepository, ProfileRepository, RecurringRepository, TransactionRepository
from .services import AccountService, RecurringService, TransactionService
from .services.recurring import ORIGIN

log = logging.getLogger("finode.recurring")
FIRST_RUN_DELAY_SECONDS = 60


def run_once(today: date | None = None) -> int:
    """Record what is due for every user; returns how many transactions were recorded."""
    today = today or local_today()
    recorded = 0
    with context.session_factory() as db:
        users = RecurringRepository.users_with_due(db, today)
    for uid in users:
        try:
            with context.session_factory() as db:
                ar, tr, pr = AccountRepository(db, uid), TransactionRepository(db, uid), ProfileRepository(db, uid)
                service = RecurringService(
                    RecurringRepository(db, uid),
                    AccountService(ar, tr, pr),
                    TransactionService(tr, ar, pr, origin=ORIGIN),
                )
                recorded += service.process_due(today)
        except Exception:  # one user's trouble must not stop the others
            log.exception("recurring transactions failed for user %s", uid)
    return recorded


async def _loop(interval_seconds: float) -> None:
    await asyncio.sleep(FIRST_RUN_DELAY_SECONDS)
    while True:
        try:
            count = await anyio.to_thread.run_sync(run_once)
            if count:
                log.info("recorded %d recurring transactions", count)
        except Exception:
            log.exception("recurring run failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan():
    minutes = settings.recurring_interval_minutes
    if minutes <= 0:
        yield
        return
    task = asyncio.create_task(_loop(minutes * 60))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
