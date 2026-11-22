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

from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from ..models.account import Account
from ..repositories import AccountRepository, ProfileRepository, TransactionRepository
from ..repositories.recurring import RecurringRepository
from ..schemas.cash_flow import AccountMove, ConversionPlan, EntryChange
from ..services.account import AccountService
from ..services.account_types import TYPE_NAMES
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


def _choices(accounts: list[Account], retire: list[str], types: list[str]) -> tuple[set[UUID], dict[UUID, str]]:
    """The accounts named by path ("Assets:Gadgets"), and the types named by name or key."""
    by_id = {a.id: a for a in accounts}

    def path(a: Account) -> str:
        names = [a.name]
        while a.parent_id is not None and a.parent_id in by_id:
            a = by_id[a.parent_id]
            names.append(a.name)
        return ":".join(reversed(names))

    by_path = {path(a): a.id for a in accounts}

    def find(text: str) -> UUID:
        if text not in by_path:
            raise ValueError(f"no account at '{text}'!")
        return by_path[text]

    named = {name.casefold(): key for key, name in TYPE_NAMES.items()} | {key: key for key in TYPE_NAMES}
    chosen: dict[UUID, str] = {}
    for item in types:
        where, _, kind = item.rpartition("=")
        if kind.casefold() not in named:
            raise ValueError(f"'{kind}' is not a type: use Cash, Bank Account, Credit Card or Prepaid Wallet!")
        chosen[find(where)] = named[kind.casefold()]
    return {find(text) for text in retire}, chosen


def _outside_the_budget(db: Session, user: UUID) -> set[UUID]:
    """The accounts the old budget flag (`accounts.on_budget`) kept outside the budget, read from the table while the
    column is still there (a database not yet past migration f9b1d3e5a7c0); none once it is gone."""
    query = text("SELECT id FROM accounts WHERE user_id = :user AND NOT on_budget").bindparams(
        bindparam("user", type_=Uuid())
    )
    try:
        rows = db.connection().execute(query, {"user": user}).all()
    except DBAPIError:
        db.rollback()
        return set()
    return {row[0] if isinstance(row[0], UUID) else UUID(str(row[0])) for row in rows}


def main(argv: list[str], session_factory: Callable[[], Session]) -> int:
    parser = argparse.ArgumentParser(prog="python -m finode.commands.cash_flow")
    parser.add_argument("--user", required=True, type=UUID, help="the person's id")
    parser.add_argument("--apply", action="store_true", help="carry the plan out (otherwise only show it)")
    parser.add_argument("--backup", type=Path, help="the database backup taken just before (required with --apply)")
    parser.add_argument(
        "--retire", action="append", default=[], metavar="PATH", help="retire this account or group too (repeatable)"
    )
    parser.add_argument(
        "--as",
        dest="types",
        action="append",
        default=[],
        metavar="PATH=TYPE",
        help="this account or group's accounts become TYPE: Cash, Bank Account, Credit Card or Prepaid Wallet",
    )
    args = parser.parse_args(argv)
    if args.apply and (args.backup is None or not args.backup.is_file() or args.backup.stat().st_size == 0):
        _say("--apply needs --backup naming a backup file that exists and is not empty.")
        return 2
    with session_factory() as db:
        conversion = _conversion(db, args.user)
        accounts = conversion.ar.list()
        off_budget = _outside_the_budget(db, args.user)
        try:
            retire_ids, types = _choices(accounts, args.retire, args.types)
            plan = conversion.plan(off_budget, strict=True, retire_ids=retire_ids, types=types)
        except ValueError as e:
            _say(f"Nothing changed: {e}")
            return 4
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
