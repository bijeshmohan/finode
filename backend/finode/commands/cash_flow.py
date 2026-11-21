"""Convert one person's books to cash flow (services/cash_flow.py).

    python -m finode.commands.cash_flow --user <id>                                  # dry run: shows, changes nothing
    python -m finode.commands.cash_flow --user <id> --apply --backup <dump file>     # the real run

The real run needs a backup file that exists and is not empty, and a dry run with nothing left to decide. Exit codes:
0 done (or dry run shown), 2 no usable backup, 3 something needs a decision first.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from sqlmodel import Session

from ..repositories import AccountRepository, ProfileRepository, TransactionRepository
from ..repositories.recurring import RecurringRepository
from ..schemas.cash_flow import AccountMove, ConversionPlan, EntryChange
from ..services.account import AccountService
from ..services.cash_flow import CashFlowConversion
from ..services.category import CategoryService


def _conversion(db: Session, user: UUID) -> CashFlowConversion:
    tr = TransactionRepository(db, user)
    accounts = AccountService(AccountRepository(db, user, origin="convert"), tr, ProfileRepository(db, user))
    return CashFlowConversion(accounts, tr, RecurringRepository(db, user), CategoryService(accounts))


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def _show(plan: ConversionPlan) -> None:
    def section(title: str, rows: list[str]) -> None:
        _say(f"{title} ({len(rows)})")
        for row in rows:
            _say(f"  {row}")

    def moves(items: list[AccountMove]) -> list[str]:
        return [f"{m.path} → {m.becomes}" for m in items]

    def changes(items: list[EntryChange]) -> list[str]:
        return [c.summary for c in items]

    section("Retired", moves(plan.retired))
    section("Moved", moves(plan.moved))
    section("Rewritten", changes(plan.rewritten))
    section("Deleted", changes(plan.deleted))
    section("New categories", plan.new_categories)
    section("Overspent months (a payment lands in a category with nothing assigned)", plan.overspent_months)
    section("Needs a decision", [*plan.undecided_accounts, *changes(plan.undecided_entries)])


def main(argv: list[str], session_factory: Callable[[], Session]) -> int:
    parser = argparse.ArgumentParser(prog="python -m finode.commands.cash_flow")
    parser.add_argument("--user", required=True, type=UUID, help="the person's id")
    parser.add_argument("--apply", action="store_true", help="carry the plan out (otherwise only show it)")
    parser.add_argument("--backup", type=Path, help="the database backup taken just before (required with --apply)")
    args = parser.parse_args(argv)
    if args.apply and (args.backup is None or not args.backup.is_file() or args.backup.stat().st_size == 0):
        _say("--apply needs --backup naming a backup file that exists and is not empty.")
        return 2
    with session_factory() as db:
        conversion = _conversion(db, args.user)
        off_budget = {a.id for a in conversion.ar.list() if not a.on_budget}
        plan = conversion.plan(off_budget, strict=True)
        _show(plan)
        if not args.apply:
            return 0
        if plan.undecided_accounts or plan.undecided_entries:
            _say("Nothing changed: decide what is listed under 'Needs a decision' first.")
            return 3
        result = conversion.apply(plan)
        _say(
            f"Done: {result.rewritten} entries rewritten, {result.deleted} deleted, "
            f"{result.recurring_rewritten} recurring rules rewritten ({result.recurring_ended} ended), "
            f"{result.accounts_deleted} accounts removed."
        )
        _say(f"Categories made: {', '.join(result.categories_made) or 'none'}")
    return 0


if __name__ == "__main__":
    from ..dependencies import engine

    sys.exit(main(sys.argv[1:], lambda: Session(engine)))
