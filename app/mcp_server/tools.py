"""The tools assistants call. Each one goes through the same services as the web UI and JSON API."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from functools import wraps
from typing import Annotated, Any, Literal
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError

from ..models.transaction import PostingSide
from ..models.utils import normalize_amount
from ..routers.web.utils import validation_message
from ..schemas import AccountCreate
from ..schemas.price import PriceCreate
from ..schemas.recurring import RecurringCreate
from ..schemas.transaction import PostingCreate, TransactionCreate, TransactionRead, TransactionUpdate
from ..services.simple import simple_postings
from .accounts import AccountIndex
from .context import Services, services


INSTRUCTIONS = """\
finode is the user's personal double-entry ledger.

- Accounts form a tree under five top-level accounts: Assets, Liabilities, Equity, Income and
  Expenses. Refer to an account by its path with ':' between names (Assets:Bank:HDFC,
  Expenses:Food) or by the end of the path when that is unique (HDFC, Food). Call list_accounts
  when unsure; never invent an account: ask the user, or create it with create_account if they agree.
- Money moves from one account to another. Spending is from an asset or liability (a bank, a
  card) to an expense; a salary is from Income to an asset. Use record_transaction for these, and
  record_split only when more than two accounts are involved.
- Every account holds one commodity: a currency (INR, USD) or one of the user's own assets
  (shares, funds, coins). Totals are reported in the user's default currency. When the two
  accounts of a transaction hold different things (buying USD or shares with INR), give
  received_amount: how much arrives in the 'to' account.
- Amounts are always positive; the from/to accounts (or debit/credit sides) give the direction.
- finode never computes capital gains: selling at a profit is recorded by the user, for example
  with a split to Income:Capital Gain.
- Things that repeat (rent, salary, subscriptions) are recurring transactions: list_recurring shows
  them, create_recurring sets one up (finode then records each occurrence by itself, so do not also
  record the same payment by hand) and stop_recurring pauses one.
- Dates are YYYY-MM-DD; today's date is used when you leave the date out.
- Changes you make are marked in finode as made by this assistant. Confirm with the user before
  deleting anything, and read back what you recorded.
"""

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
IDEMPOTENT_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

AccountType = Literal["Assets", "Liabilities", "Equity", "Income", "Expenses"]
Amount = Annotated[Decimal, Field(gt=0, description="A positive amount, e.g. 450 or 0.0125")]
AccountRef = Annotated[str, Field(description="Account path such as Assets:Bank:HDFC, or a unique end of one (HDFC)")]
OptionalDate = Annotated[date | None, Field(description="YYYY-MM-DD; today when left out")]


def text(value: Decimal | None) -> str | None:
    """Amounts travel as strings so no precision is lost."""
    return None if value is None else format(normalize_amount(value), "f")


def _tool_errors(fn: Callable) -> Callable:
    """Turn the services' messages into tool errors the assistant can read and act on."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except ValidationError as e:
            raise ToolError(validation_message(e)) from e
        except KeyError as e:
            raise ToolError(str(e.args[0]) if e.args else "not found") from e
        except (ValueError, LookupError) as e:
            raise ToolError(str(e)) from e

    return wrapper


def _transaction(t: TransactionRead, index: AccountIndex, s: Services) -> dict[str, Any]:
    commodity_of = {aid: e.account.commodity for aid, e in index.entries.items()}
    total = sum((p.value for p in t.postings if p.side == PostingSide.DEBIT), Decimal(0))
    return {
        "id": str(t.tid),
        "date": t.date.isoformat(),
        "payee": t.payee,
        "note": t.comment,
        "currency": t.currency,
        "total": text(total),
        "postings": [
            {
                "account": index.path(p.account),
                "side": p.side.value,
                "amount": text(p.amount),
                "commodity": commodity_of.get(p.account),
                **({"value": text(p.value)} if commodity_of.get(p.account) != t.currency else {}),
            }
            for p in t.postings
        ],
        "created_via": _via(t.created_via),
        "updated_via": _via(t.updated_via),
    }


def _via(origin: str | None) -> str | None:
    if origin and origin.startswith("mcp:"):
        return f"assistant ({origin[4:]})"
    return origin


def _index(s: Services) -> AccountIndex:
    return AccountIndex(s.accounts.list())


def _transaction_id(value: str) -> UUID:
    try:
        return UUID(value.strip())
    except ValueError:
        raise ToolError(f"'{value}' is not a transaction id: use the id from search_transactions!")


# ---- reading ---------------------------------------------------------------------------------------


@_tool_errors
def get_overview() -> dict[str, Any]:
    """Net worth, assets and liabilities now, and this month's income and expenses so far,
    all in the user's default currency."""
    with services() as s:
        summary = s.reports.summary()
        return {
            "currency": summary.currency,
            "net_worth": text(summary.net_worth),
            "assets": text(summary.assets),
            "liabilities": text(summary.liabilities),
            "this_month": {
                "from": summary.period_start.isoformat(),
                "to": summary.period_end.isoformat(),
                "income": text(summary.income),
                "expenses": text(summary.expenses),
                "net": text(summary.net_income),
            },
            "unpriced": summary.unpriced,
            **(
                {"note": "Some holdings have no price yet, so they are left out of these totals. See get_prices."}
                if summary.unpriced
                else {}
            ),
        }


@_tool_errors
def list_accounts(
    type: Annotated[AccountType | None, Field(description="Only accounts under this top-level account")] = None,
) -> dict[str, Any]:
    """Every account with its path, what it holds and its balance. Top-level accounts show their
    total in the default currency; others show their balance in what they hold."""
    with services() as s:
        index = _index(s)
        return {
            "default_currency": s.accounts.default_currency().code,
            "accounts": [
                {
                    "path": e.path,
                    "holds": e.account.commodity,
                    "balance": text(e.account.balance),
                    "can_post": e.postable,
                    **({"unpriced": True} if e.account.unpriced else {}),
                    **({"details": e.account.details} if e.account.details and not e.is_root else {}),
                }
                for e in index.sorted()
                if type is None or e.root == type
            ],
        }


@_tool_errors
def get_account(
    account: AccountRef,
    recent: Annotated[int, Field(ge=0, le=100, description="How many recent entries to include")] = 10,
) -> dict[str, Any]:
    """One account: its balance, what a holding is worth (invested, value, gain) and its recent
    entries with a running balance. Entries of sub-accounts count towards a group."""
    with services() as s:
        index = _index(s)
        entry = index.find(account, allow_root=True)
        aid = entry.account.aid
        register = s.accounts.register(aid) or []
        holding = s.accounts.holding(aid)
        result: dict[str, Any] = {
            "path": entry.path,
            "holds": entry.account.commodity,
            "balance": text(entry.account.balance),
            "can_post": entry.postable,
            "sub_accounts": [e.path for e in index.sorted() if e.account.parent_id == aid],
            "recent": [
                {
                    "transaction_id": str(r.tid),
                    "date": r.date.isoformat(),
                    "payee": r.payee,
                    "note": r.comment,
                    "with": r.counter_accounts,
                    "change": text(r.change),
                    "balance": text(r.balance),
                }
                for r in reversed(register[-recent:] if recent else [])
            ],
        }
        if entry.account.unpriced:
            result["unpriced"] = True
        if holding:
            result["holding"] = {
                "quantity": text(holding.quantity),
                "commodity": holding.commodity,
                "currency": holding.currency,
                "value": text(holding.value),
                "invested": text(holding.invested),
                "gain": text(holding.gain),
                "rate": text(holding.rate),
                "rate_as_of": holding.rate_as_of.isoformat() if holding.rate_as_of else None,
            }
        return result


@_tool_errors
def search_transactions(
    date_from: Annotated[date | None, Field(description="On or after this day (YYYY-MM-DD)")] = None,
    date_to: Annotated[date | None, Field(description="On or before this day (YYYY-MM-DD)")] = None,
    account: Annotated[str | None, Field(description="Only transactions touching this account or its sub-accounts")] = None,
    text_contains: Annotated[str | None, Field(description="Case-insensitive text in the payee or note")] = None,
    min_amount: Annotated[Decimal | None, Field(ge=0, description="Smallest transaction total")] = None,
    max_amount: Annotated[Decimal | None, Field(ge=0, description="Largest transaction total")] = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 25,
) -> dict[str, Any]:
    """Transactions, newest first. The total is in the transaction's own currency."""
    with services() as s:
        index = _index(s)
        aid = index.find(account, allow_root=True).account.aid if account else None
        needle = (text_contains or "").casefold().strip()
        found = []
        truncated = False
        for t in s.transactions.list(account=aid, date_from=date_from, date_to=date_to):
            total = sum((p.value for p in t.postings if p.side == PostingSide.DEBIT), Decimal(0))
            if needle and needle not in f"{t.payee or ''} {t.comment or ''}".casefold():
                continue
            if min_amount is not None and total < min_amount:
                continue
            if max_amount is not None and total > max_amount:
                continue
            if len(found) == limit:
                truncated = True
                break
            found.append(_transaction(t, index, s))
        return {"transactions": found, "truncated": truncated}


@_tool_errors
def get_transaction(transaction_id: Annotated[str, Field(description="Id from search_transactions")]) -> dict[str, Any]:
    """One transaction with all its postings."""
    with services() as s:
        t = s.transactions.read(_transaction_id(transaction_id))
        if t is None:
            raise ToolError("transaction not found")
        return _transaction(t, _index(s), s)


@_tool_errors
def spending_breakdown(
    kind: Annotated[Literal["expenses", "income"], Field(description="Expenses or income")] = "expenses",
    date_from: Annotated[date | None, Field(description="First day; the 1st of this month when left out")] = None,
    date_to: Annotated[date | None, Field(description="Last day; today when left out")] = None,
    depth: Annotated[int, Field(ge=1, le=20, description="1 = Food, Rent...; 2 = Food:Groceries...")] = 1,
) -> dict[str, Any]:
    """Expenses (or income) for a period per account, largest first, in the default currency."""
    with services() as s:
        report = s.reports.breakdown("Expenses" if kind == "expenses" else "Income", date_from, date_to, depth)
        return {
            "kind": kind,
            "currency": report.currency,
            "from": report.period_start.isoformat(),
            "to": report.period_end.isoformat(),
            "total": text(report.total),
            "by_account": [{"account": line.account.replace(" › ", ":"), "amount": text(line.amount)} for line in report.lines],
            **({"unpriced": True} if report.unpriced else {}),
        }


@_tool_errors
def get_prices(
    commodity: Annotated[str | None, Field(description="Only prices of this code, e.g. USD or INFY")] = None,
) -> dict[str, Any]:
    """The user's own assets, the prices they entered, and today's rate of everything their
    accounts hold in the default currency (from those prices or their own conversions)."""
    with services() as s:
        default = s.accounts.default_currency()
        held = sorted(
            {a.commodity for a in s.accounts.list() if a.parent_id is not None and a.commodity and a.commodity != default.code}
        )
        today = date.today()
        rates = []
        for code in held:
            rate = s.prices.rate(code, default.code, today)
            rates.append(
                {
                    "commodity": code,
                    "rate": text(rate.rate),
                    "as_of": rate.as_of.isoformat() if rate.as_of else None,
                    **({"note": "no price yet: set one with set_price"} if rate.rate is None else {}),
                }
            )
        return {
            "default_currency": default.code,
            "assets": [
                {"code": c.code, "name": c.name, "kind": c.kind, "decimals": c.decimals}
                for c in s.commodities.list()
                if c.kind != "currency"
            ],
            "rates_today": rates,
            "prices": [
                {"commodity": p.commodity, "quote": p.quote, "date": p.date.isoformat(), "price": text(p.price)}
                for p in s.prices.list(commodity)
            ],
        }


@_tool_errors
def list_recurring() -> dict[str, Any]:
    """The user's recurring transactions (rent, salary, subscriptions): who pays whom, how often, and
    when the next one is due."""
    with services() as s:
        index = _index(s)
        rules = s.recurring.list()
        return {
            "recurring": [
                {
                    "id": str(r.rid),
                    "from": index.path(r.from_account),
                    "to": index.path(r.to_account),
                    "amount": text(r.amount),
                    **({"received_amount": text(r.received_amount)} if r.received_amount else {}),
                    "payee": r.payee,
                    "note": r.comment,
                    "every": f"{r.every} {r.frequency}" if r.every != 1 else r.frequency,
                    "start_date": r.start_date.isoformat(),
                    "end_date": r.end_date.isoformat() if r.end_date else None,
                    "next_due": r.next_date.isoformat() if r.active else None,
                    "status": "active" if r.active else "paused or ended",
                    **({"problem": r.last_error} if r.last_error else {}),
                }
                for r in rules
            ]
        }


# ---- writing ---------------------------------------------------------------------------------------


@_tool_errors
def record_transaction(
    amount: Annotated[Amount, Field(description="How much leaves the 'from' account")],
    from_account: Annotated[str, Field(description="Where the money comes from, e.g. Assets:Bank:HDFC or Liabilities:Card")],
    to_account: Annotated[str, Field(description="Where it goes, e.g. Expenses:Food")],
    date: OptionalDate = None,
    payee: Annotated[str | None, Field(max_length=40)] = None,
    note: Annotated[str | None, Field(max_length=200)] = None,
    received_amount: Annotated[
        Decimal | None,
        Field(gt=0, description="Only when the accounts hold different things: how much arrives in 'to_account'"),
    ] = None,
) -> dict[str, Any]:
    """Record money moving from one account to another: spending, income, a transfer, or a
    conversion (buying USD, shares or coins)."""
    with services() as s:
        index = _index(s)
        source = index.find(from_account, postable=True)
        target = index.find(to_account, postable=True)
        currency, postings = simple_postings(
            s.accounts, amount, received_amount, source.account.aid, target.account.aid
        )
        saved = s.transactions.create(
            TransactionCreate(
                date=date or _today(),
                payee=(payee or "").strip() or None,
                comment=(note or "").strip() or None,
                currency=currency,
                postings=postings,
            )
        )
        return {"recorded": _transaction(saved, index, s)}


class PostingIn(BaseModel):
    account: AccountRef
    side: Literal["debit", "credit"] = Field(
        description="debit: money into an asset or expense (or paying down a liability); credit: the other way"
    )
    amount: Amount
    value: Decimal | None = Field(
        default=None,
        gt=0,
        description="What this row is worth in the transaction's currency; only when its account holds something else",
    )


def _postings(index: AccountIndex, rows: list[PostingIn]) -> list[PostingCreate]:
    return [
        PostingCreate(
            account=index.find(row.account, postable=True).account.aid,
            side=PostingSide(row.side),
            amount=row.amount,
            value=row.value,
        )
        for row in rows
    ]


@_tool_errors
def record_split(
    postings: Annotated[list[PostingIn], Field(min_length=2, description="Debits and credits; they must balance")],
    date: OptionalDate = None,
    payee: Annotated[str | None, Field(max_length=40)] = None,
    note: Annotated[str | None, Field(max_length=200)] = None,
    currency: Annotated[str | None, Field(description="What the transaction balances in; the default currency when left out")] = None,
) -> dict[str, Any]:
    """Record a transaction with several rows, e.g. a bill split across categories or a salary
    with deductions. Debits must equal credits."""
    with services() as s:
        index = _index(s)
        saved = s.transactions.create(
            TransactionCreate(
                date=date or _today(),
                payee=(payee or "").strip() or None,
                comment=(note or "").strip() or None,
                currency=currency,
                postings=_postings(index, postings),
            )
        )
        return {"recorded": _transaction(saved, index, s)}


@_tool_errors
def update_transaction(
    transaction_id: Annotated[str, Field(description="Id from search_transactions")],
    date: Annotated[date | None, Field(description="New date (YYYY-MM-DD)")] = None,
    payee: Annotated[str | None, Field(max_length=40, description="New payee; an empty string clears it")] = None,
    note: Annotated[str | None, Field(max_length=200, description="New note; an empty string clears it")] = None,
    postings: Annotated[
        list[PostingIn] | None, Field(description="All the rows again, replacing the old ones; leave out to keep them")
    ] = None,
    currency: Annotated[str | None, Field(description="New currency; only together with postings")] = None,
) -> dict[str, Any]:
    """Change a transaction. Only what you pass changes."""
    tid = _transaction_id(transaction_id)
    with services() as s:
        index = _index(s)
        if s.transactions.read(tid) is None:
            raise ToolError("transaction not found")
        changes: dict[str, Any] = {}
        if date is not None:
            changes["date"] = date
        if payee is not None:
            changes["payee"] = payee.strip() or None
        if note is not None:
            changes["comment"] = note.strip() or None
        if postings is not None:
            changes["postings"] = _postings(index, postings)
        if currency is not None:
            changes["currency"] = currency
        if not changes:
            raise ToolError("nothing to change: pass a date, payee, note or postings!")
        saved = s.transactions.update(tid, TransactionUpdate(**changes))
        return {"updated": _transaction(saved, index, s)}


@_tool_errors
def delete_transaction(transaction_id: Annotated[str, Field(description="Id from search_transactions")]) -> dict[str, Any]:
    """Delete a transaction for good. Ask the user to confirm first."""
    tid = _transaction_id(transaction_id)
    with services() as s:
        index = _index(s)
        existing = s.transactions.read(tid)
        if existing is None:
            raise ToolError("transaction not found")
        s.transactions.delete(tid)
        return {"deleted": _transaction(existing, index, s)}


@_tool_errors
def create_account(
    name: Annotated[str, Field(max_length=40, description="The new account's own name, without ':'")],
    parent: Annotated[str, Field(description="Where it goes, e.g. Expenses or Assets:Bank")],
    holds: Annotated[str | None, Field(description="Currency or asset code; the parent's when left out")] = None,
    opening_balance: Annotated[
        Decimal | None, Field(ge=0, description="Assets and liabilities only: what it holds (or owes) today")
    ] = None,
    opening_value: Annotated[
        Decimal | None,
        Field(gt=0, description="What the opening balance is worth in the default currency, when it holds something else and has no price"),
    ] = None,
    details: Annotated[str | None, Field(max_length=200)] = None,
) -> dict[str, Any]:
    """Add an account. Check list_accounts first so you don't create a duplicate."""
    with services() as s:
        index = _index(s)
        parent_entry = index.find(parent, allow_root=True)
        name = name.strip()
        siblings = [e for e in index.entries.values() if e.account.parent_id == parent_entry.account.aid]
        twin = next((e for e in siblings if e.account.name.casefold() == name.casefold()), None)
        if twin:
            raise ToolError(f"'{parent_entry.path}' already has an account named '{twin.account.name}': use {twin.path}!")
        if opening_balance and parent_entry.root not in ("Assets", "Liabilities"):
            raise ToolError("only asset and liability accounts have an opening balance!")
        created = s.accounts.create(
            AccountCreate(
                name=name,
                details=(details or "").strip() or None,
                parent_id=parent_entry.account.aid,
                commodity=holds,
                balance=opening_balance or Decimal("0.00"),
                balance_value=opening_value,
            )
        )
        return {
            "created": {
                "path": f"{parent_entry.path}:{created.name}",
                "holds": created.commodity,
                "balance": text(created.balance),
            }
        }


@_tool_errors
def set_price(
    commodity: Annotated[str, Field(description="What is priced, e.g. INFY or USD")],
    price: Annotated[Amount, Field(description="What one unit is worth")],
    quote: Annotated[str | None, Field(description="What the price is in; the default currency when left out")] = None,
    date: OptionalDate = None,
) -> dict[str, Any]:
    """Set the price of an asset or an exchange rate for a day (replacing one already set for that day)."""
    with services() as s:
        saved = s.prices.set(
            PriceCreate(
                commodity=commodity,
                quote=quote or s.accounts.default_currency().code,
                date=date or _today(),
                price=price,
            )
        )
        return {
            "saved": {"commodity": saved.commodity, "quote": saved.quote, "date": saved.date.isoformat(), "price": text(saved.price)}
        }


@_tool_errors
def create_recurring(
    amount: Annotated[Amount, Field(description="How much leaves the 'from' account each time")],
    from_account: AccountRef,
    to_account: AccountRef,
    frequency: Annotated[Literal["daily", "weekly", "monthly", "yearly"], Field(description="The unit between occurrences")] = "monthly",
    every: Annotated[int, Field(ge=1, le=366, description="Every N units: 2 with weekly is fortnightly")] = 1,
    start_date: Annotated[date | None, Field(description="First occurrence, YYYY-MM-DD; today when left out. Past dates are recorded right away")] = None,
    end_date: Annotated[date | None, Field(description="Last possible occurrence; none when left out")] = None,
    payee: Annotated[str | None, Field(max_length=40)] = None,
    note: Annotated[str | None, Field(max_length=200)] = None,
    received_amount: Annotated[Decimal | None, Field(gt=0, description="Only when the accounts hold different things")] = None,
) -> dict[str, Any]:
    """Set up a transaction that finode records by itself on a schedule (rent, salary, a subscription).
    Check list_recurring first so you don't create a duplicate."""
    with services() as s:
        index = _index(s)
        source = index.find(from_account, postable=True)
        target = index.find(to_account, postable=True)
        created = s.recurring.create(
            RecurringCreate(
                from_account=source.account.aid,
                to_account=target.account.aid,
                amount=amount,
                received_amount=received_amount,
                payee=payee,
                comment=note,
                frequency=frequency,
                every=every,
                start_date=start_date or _today(),
                end_date=end_date,
            )
        )
        s.recurring.process_due()
        rule = s.recurring.read(created.rid)
        return {
            "created": {
                "id": str(rule.rid),
                "from": source.path,
                "to": target.path,
                "amount": text(rule.amount),
                "every": f"{rule.every} {rule.frequency}" if rule.every != 1 else rule.frequency,
                "next_due": rule.next_date.isoformat() if rule.active else None,
            }
        }


@_tool_errors
def stop_recurring(
    recurring_id: Annotated[str, Field(description="The id from list_recurring")],
) -> dict[str, Any]:
    """Pause a recurring transaction: nothing more is recorded until the user resumes it in finode.
    What it already recorded is kept."""
    with services() as s:
        try:
            rid = UUID(recurring_id.strip())
        except ValueError:
            raise ToolError(f"'{recurring_id}' is not a recurring transaction id: use the id from list_recurring!")
        rule = s.recurring.set_active(rid, False)
        if rule is None:
            raise ToolError("no recurring transaction has that id!")
        return {"paused": str(rule.rid)}


def _today() -> date:
    return date.today()


# ---- prompts ---------------------------------------------------------------------------------------


def monthly_review(month: Annotated[str | None, Field(description="YYYY-MM; this month when left out")] = None) -> str:
    """Review a month: where the money went and how net worth moved."""
    period = f"the month {month}" if month else "this month so far"
    return (
        f"Give me a short review of {period} in finode. Use get_overview for net worth, "
        "spending_breakdown for expenses and income by account (compare with the month before), "
        "and search_transactions for the largest expenses. Point out anything unusual and anything "
        "unpriced. Keep it brief and use my default currency."
    )


READ_TOOLS = [
    get_overview, list_accounts, get_account, search_transactions, get_transaction, spending_breakdown, get_prices,
    list_recurring,
]
WRITE_TOOLS = [
    (record_transaction, WRITE),
    (record_split, WRITE),
    (update_transaction, IDEMPOTENT_WRITE),
    (delete_transaction, DESTRUCTIVE),
    (create_account, WRITE),
    (set_price, IDEMPOTENT_WRITE),
    (create_recurring, WRITE),
    (stop_recurring, IDEMPOTENT_WRITE),
]


READ_ONLY_MESSAGE = (
    "This connection is read-only, so nothing was changed. The user can allow changes in finode under "
    "Profile > AI assistants (Change access), and then you can try again."
)
READ_ONLY_NOTE = (
    "\nThis connection is read-only: the tools that change things are listed but always refuse. If the user asks "
    "for a change, say so and tell them to allow read & write access in finode under Profile > AI assistants.\n"
)


def _refused(fn: Callable) -> Callable:
    """The same tool for a read-only connection: it keeps its name and arguments but only explains."""

    @wraps(fn)
    def refuse(*args, **kwargs):
        raise ToolError(READ_ONLY_MESSAGE)

    summary = (fn.__doc__ or fn.__name__).strip().splitlines()[0]
    refuse.__doc__ = f"Unavailable: this connection is read-only. (Would otherwise: {summary})"
    return refuse


def build_server(write: bool) -> MCPServer:
    server = MCPServer(
        name="finode",
        title="finode",
        instructions=INSTRUCTIONS if write else INSTRUCTIONS + READ_ONLY_NOTE,
        website_url="https://finode.bijesh.me",
    )
    for fn in READ_TOOLS:
        server.add_tool(fn, annotations=READ)
    for fn, annotations in WRITE_TOOLS:
        server.add_tool(fn if write else _refused(fn), annotations=annotations)
    server.prompt()(monthly_review)
    return server
