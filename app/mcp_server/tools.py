"""The tools assistants call. Each one goes through the same services as the web UI and JSON API."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from functools import wraps
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError

from ..clock import local_start_utc, local_today
from ..config import settings
from ..models.api_token import TokenScope
from ..models.transaction import PostingSide
from ..models.utils import normalize_amount
from ..routers.web.utils import validation_message
from ..schemas import AccountCreate
from ..schemas.account import AccountChangeRead
from ..schemas.recurring import RecurringCreate
from ..schemas.transaction import (
    MAX_BATCH,
    ChangeRead,
    PostingCreate,
    TransactionCreate,
    TransactionPreview,
    TransactionRead,
    TransactionUpdate,
)
from ..services.simple import simple_postings
from ..version import VERSION
from .accounts import AccountIndex
from .context import Services, services

INSTRUCTIONS = """\
finode is the user's personal double-entry ledger.

- Accounts form a tree under five top-level accounts: Assets, Liabilities, Equity, Income and
  Expenses. Refer to an account by its path with ':' between names (Assets:Bank:HDFC,
  Expenses:Food) or by the end of the path when that is unique (HDFC, Food). Call list_accounts
  when unsure; never invent an account: ask the user, or create it with create_account if they agree.
  New users start with built-in groups under Assets (Bank Accounts, Cash, Investments) and Liabilities
  (Credit Cards, Loans); they cannot be changed or removed. Put a bank under Bank Accounts and a card under
  Credit Cards (they start as part of the budget), a fund under Investments and a loan under Loans (they
  start outside the budget).
- Every account has an id (list_accounts, get_account). An id survives renames and moves, a path does not: keep
  ids when you remember an account, and give either to any tool that takes an account.
- Call get_status first when unsure what this connection may do, how much room is left today, or when the books
  last changed.
- Tags are #hashtags written in a transaction's note ("Dinner #reimbursable"): to tag an entry, put the #tag in its
  note (keep the user's own words, update_transaction replaces the note); list_tags shows the tags in use and
  search_transactions(tag=) finds the entries. Reuse an existing tag instead of inventing a near-duplicate.
- check_balance sets a statement's balance against the books and points at the entries that could explain a gap.
- payee_defaults tells how the user usually books a payee (which accounts); use it before guessing a category.
- get_account_history shows what happened to one account and who did it (renames, moves, closings); recent_changes(what='accounts') lists the latest across all of them.
- get_transaction_history shows what happened to one transaction and who did it, with each edit's exact changes;
  recent_changes lists the latest changes of all of them (by='assistant' for what assistants did). Look there
  before assuming who changed something.
- Entries that come from outside finode (a bank SMS, a mail, a UPI app) should carry source (a short kind: gmail,
  upi...) and external_id (the reference that source gave it) when you record them. Recording the same pair again
  returns the entry already made (already_recorded) instead of a copy, so retrying is safe; search_transactions
  finds an entry by them. Search before recording something that may be there already.
- To record many entries at once (a statement, an EMI schedule), use record_transactions: up to 50, all saved or
  none, each with its own source and external_id so sending it again skips what is already there. Its dry_run
  shows the whole batch first.
- To show the user what a change would do before making it, pass dry_run=true to record_transaction, record_split,
  update_transaction or delete_transaction: every rule is checked and the answer says what would be saved, with
  nothing saved. It also works when the connection may only read.
- Money moves from one account to another. Spending is from an asset or liability (a bank, a
  card) to an expense; a salary is from Income to an asset. Use record_transaction for these, and
  record_split only when more than two accounts are involved.
- finode keeps everything in one currency, the user's own (shown by get_overview and list_accounts);
  there are no other currencies, shares or coins, and amounts are plain numbers in that currency.
- Amounts are always positive; the from/to accounts (or debit/credit sides) give the direction.
- Things that repeat (rent, salary, subscriptions) are recurring transactions: list_recurring shows
  them, create_recurring sets one up (finode then records each occurrence by itself, so do not also
  record the same payment by hand; give postings instead of from/to/amount for a split), stop_recurring
  pauses one and skip_recurring_occurrence leaves out just the next occurrence.
- A refund, reversal or cash-back can be linked to the earlier transaction with related_to (its id); it is a link
  only and changes no amount. Deleted transactions can be listed (list_deleted_transactions) and brought back
  (restore_transaction); resume_recurring restarts a paused recurring transaction.
- Dates are YYYY-MM-DD; today's date is used when you leave the date out. Balances count entries
  up to today: an entry dated in the future shows once its day comes.
- The budget gives every unit of money a job (envelopes): get_budget shows what is ready to assign and each
  expense category's assigned, spent and available amounts (goals, money being saved for something by a month, are listed
  under `goals`, not in `categories`, and are not counted in assigned/spent/available_total); assign_to_category plans a month's money and
  move_budget_money shifts it between categories; create_goal, update_goal and delete_goal manage goals; assign_to_goal sets money aside for a goal and use_goal hands what a goal saved to a
  category that paid for something. These only change the plan, never the ledger, and the
  user chooses which accounts are part of the budget. Never assign more than is ready to assign unless asked.
- check_books confirms that debits equal credits in every transaction and overall; use it when the
  user doubts their numbers.
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
Source = Annotated[
    str | None,
    Field(max_length=40, description="Where it came from outside finode, a short kind such as gmail, upi or bank-sms"),
]
ExternalId = Annotated[
    str | None,
    Field(
        max_length=120,
        description="The reference that source gave it (a UPI reference, a card authorisation code, a message id). "
        "It needs a source. Recording the same source and reference again returns the entry already made "
        "instead of a copy",
    ),
]
SourceUrl = Annotated[str | None, Field(max_length=500, description="A web link back to the source")]
DryRun = Annotated[
    bool,
    Field(
        description="Only check: run every rule and answer with what would be saved, without saving anything. "
        "Works on a read-only connection too, so it is the safe way to show the user a change before they allow it"
    ),
]
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
    total = sum((p.amount for p in t.postings if p.side == PostingSide.DEBIT), Decimal(0))
    return {
        "id": str(t.tid),
        "date": t.date.isoformat(),
        "payee": t.payee,
        "note": t.comment,
        **({"tags": t.tags} if t.tags else {}),
        "total": text(total),
        "postings": [
            {
                "account": index.path(p.account),
                "account_id": str(p.account),
                "side": p.side.value,
                "amount": text(p.amount),
            }
            for p in t.postings
        ],
        "related_to": str(t.related_id) if t.related_id else None,
        "reference": {"source": t.source, "external_id": t.external_id, "url": t.source_url}
        if t.source or t.external_id or t.source_url
        else None,
        "created_via": _via(t.created_via),
        "updated_via": _via(t.updated_via),
    }


def _via(origin: str | None) -> str | None:
    if origin and origin.startswith("mcp:"):
        return f"assistant ({origin[4:]})"
    return origin


def _index(s: Services) -> AccountIndex:
    return AccountIndex(s.accounts.list())


def _related_id(value: str | None) -> UUID | None:
    return _transaction_id(value) if value and value.strip() else None


def _transaction_id(value: str) -> UUID:
    try:
        return UUID(value.strip())
    except ValueError:
        raise ToolError(f"'{value}' is not a transaction id: use the id from search_transactions!") from None


# ---- reading ---------------------------------------------------------------------------------------


@_tool_errors
def get_overview() -> dict[str, Any]:
    """Net worth, assets and liabilities now, and this month's income and expenses so far,
    all in the user's currency."""
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
        }


@_tool_errors
def list_accounts(
    type: Annotated[AccountType | None, Field(description="Only accounts under this top-level account")] = None,
    include_closed: Annotated[
        bool, Field(description="Also list accounts the user has closed (they cannot be posted to)")
    ] = False,
) -> dict[str, Any]:
    """Every account with its id, path, type, balance and what it is for (details). Top-level accounts show the total of everything inside.
    Assets and liabilities say whether they are part of the budget (on_budget) and, when not, which expense category
    their payments are budgeted under."""
    with services() as s:
        index = _index(s)
        return {
            "currency": s.accounts.currency().code,
            "accounts": [
                {
                    "id": str(e.account.aid),
                    "path": e.path,
                    "type": e.root,
                    "balance": text(e.account.balance),
                    "can_post": e.postable and e.account.closed_on is None,
                    "details": None if e.is_root else e.account.details,
                    **({"closed": e.account.closed_on.isoformat()} if e.account.closed_on else {}),
                    **(_budget_facts(e, index) if not e.is_root and e.root in ("Assets", "Liabilities") else {}),
                    **({"group": e.account.system_key} if e.account.system_key else {}),
                }
                for e in index.sorted()
                if (type is None or e.root == type) and (include_closed or e.account.closed_on is None)
            ],
        }


def _budget_facts(e, index: AccountIndex) -> dict[str, Any]:
    """Whether an asset or liability is part of the budget, and where its payments are budgeted when it is not."""
    facts: dict[str, Any] = {"on_budget": e.account.on_budget}
    if e.account.payment_category_id:
        facts["payment_category"] = index.path(e.account.payment_category_id)
    return facts


@_tool_errors
def get_account(
    account: AccountRef,
    recent: Annotated[int, Field(ge=0, le=100, description="How many recent entries to include")] = 10,
) -> dict[str, Any]:
    """One account: its balance and its recent entries with a running balance. Entries of sub-accounts count towards a group."""
    with services() as s:
        index = _index(s)
        entry = index.find(account, allow_root=True)
        aid = entry.account.aid
        register = s.accounts.register(aid) or []
        result: dict[str, Any] = {
            "id": str(aid),
            "path": entry.path,
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
        return result


@_tool_errors
def search_transactions(
    date_from: Annotated[date | None, Field(description="On or after this day (YYYY-MM-DD)")] = None,
    date_to: Annotated[date | None, Field(description="On or before this day (YYYY-MM-DD)")] = None,
    account: Annotated[
        str | None, Field(description="Only transactions touching this account or its sub-accounts")
    ] = None,
    payee: Annotated[str | None, Field(description="Exactly this payee, capitals aside")] = None,
    text_contains: Annotated[str | None, Field(description="Case-insensitive text in the payee or note")] = None,
    kind: Annotated[
        Literal["expense", "income", "transfer"] | None, Field(description="Only spending, income or transfers")
    ] = None,
    min_amount: Annotated[Decimal | None, Field(ge=0, description="Smallest transaction total")] = None,
    max_amount: Annotated[Decimal | None, Field(ge=0, description="Largest transaction total")] = None,
    tag: Annotated[
        str | None, Field(description="Only entries whose note has this #hashtag (#reimbursable or reimbursable)")
    ] = None,
    source: Annotated[str | None, Field(description="Only entries from this source (gmail, upi...)")] = None,
    external_id: Annotated[
        str | None, Field(description="Only the entry with this reference (use with source)")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 25,
    offset: Annotated[int, Field(ge=0, description="How many matches to skip, to read the next page")] = 0,
) -> dict[str, Any]:
    """Transactions, newest first. Besides the page asked for, the answer counts every match (`count`) and adds
    them up (`spent`, `earned`, `transferred`, and `account_net_change` when an account is given), so there is no
    need to page through everything to total it."""
    with services() as s:
        index = _index(s)
        entry = index.find(account, allow_root=True) if account else None
        needle = (text_contains or "").casefold().strip()
        matches: list[tuple[TransactionRead, Decimal]] = []
        for t in s.transactions.list(
            account=entry.account.aid if entry else None,
            date_from=date_from,
            date_to=date_to,
            kind=kind,
            payee=payee,
            source=source,
            external_id=external_id,
            tag=tag,
        ):
            total = sum((p.amount for p in t.postings if p.side == PostingSide.DEBIT), Decimal(0))
            if needle and needle not in f"{t.payee or ''} {t.comment or ''}".casefold():
                continue
            if min_amount is not None and total < min_amount:
                continue
            if max_amount is not None and total > max_amount:
                continue
            matches.append((t, total))
        sums = {"expense": Decimal(0), "income": Decimal(0), "transfer": Decimal(0)}
        for t, total in matches:
            sums[_kind(t, index)] += total
        page = matches[offset : offset + limit]
        result: dict[str, Any] = {
            "transactions": [_transaction(t, index, s) for t, _ in page],
            "count": len(matches),
            "offset": offset,
            "truncated": offset + limit < len(matches),
            "spent": text(sums["expense"]),
            "earned": text(sums["income"]),
            "transferred": text(sums["transfer"]),
        }
        if entry:
            result["account_net_change"] = text(_net_change(matches, entry, index))
        return result


def _kind(t: TransactionRead, index: AccountIndex) -> str:
    """Told apart as the Transactions page does: a debit to Expenses is spending, else a credit to Income is income."""
    roots = [(p.side, index.entries[p.account].root if p.account in index.entries else "") for p in t.postings]
    if any(side == PostingSide.DEBIT and root == "Expenses" for side, root in roots):
        return "expense"
    if any(side == PostingSide.CREDIT and root == "Income" for side, root in roots):
        return "income"
    return "transfer"


def _net_change(matches: list[tuple[TransactionRead, Decimal]], entry, index: AccountIndex) -> Decimal:
    """What the matches did to the account and everything inside it: up for its own kind of side, down for the other."""
    inside = {e.account.aid for e in index.entries.values() if e.segments[: len(entry.segments)] == entry.segments}
    debit_normal = entry.root in ("Assets", "Expenses")
    change = Decimal(0)
    for t, _ in matches:
        for p in t.postings:
            if p.account in inside:
                up = (p.side == PostingSide.DEBIT) == debit_normal
                change += p.amount if up else -p.amount
    return change


@_tool_errors
def get_transaction(transaction_id: Annotated[str, Field(description="Id from search_transactions")]) -> dict[str, Any]:
    """One transaction with all its postings."""
    with services() as s:
        t = s.transactions.read(_transaction_id(transaction_id))
        if t is None:
            raise ToolError("transaction not found")
        index = _index(s)
        found = _transaction(t, index, s)
        found["related"] = [
            {"id": str(r.tid), "date": r.date.isoformat(), "payee": r.payee} for r in s.transactions.related(t.tid)
        ]
        return found


def _plain(value: Any) -> Any:
    """History data for an assistant: amounts as strings, account paths with ':'."""
    if isinstance(value, Decimal):
        return text(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, str):
        return value.replace(" › ", ":")
    return value


def _step(c: ChangeRead, full: bool) -> dict[str, Any]:
    e = c.entry
    debits = sum((p.amount for p in e.postings if p.side == PostingSide.DEBIT), Decimal(0))
    step: dict[str, Any] = {
        "at": c.at.isoformat(),
        "action": c.action,
        "by": _via(c.via),
        "transaction_id": str(c.transaction),
    }
    if full or c.action != "updated":
        step["entry"] = _plain(
            {
                "date": e.date.isoformat(),
                "payee": e.payee,
                "note": e.comment,
                "total": e.postings and debits,
                "postings": [{"account": p.account, "side": p.side.value, "amount": p.amount} for p in e.postings],
                "reference": {"source": e.source, "external_id": e.external_id, "url": e.source_url}
                if e.source or e.external_id or e.source_url
                else None,
            }
        )
    else:
        step["entry"] = {"date": e.date.isoformat(), "payee": e.payee, "total": text(debits)}
    if c.changes:
        step["changes"] = _plain(c.changes)
    return step


@_tool_errors
def check_balance(
    account: AccountRef,
    statement_balance: Annotated[
        Decimal, Field(description="The balance the bank or card statement shows (for a card or loan: what is owed)")
    ],
    as_of: Annotated[date | None, Field(description="The statement's day (YYYY-MM-DD); today when left out")] = None,
    days: Annotated[int, Field(ge=0, le=90, description="How many days back to list entries")] = 14,
) -> dict[str, Any]:
    """Set a bank or card statement's balance against finode's books on the same day. Says whether they agree, by
    how much they differ, and lists the recent entries, marking those exactly as large as the difference (the
    likely missing or extra one). Nothing is changed."""
    with services() as s:
        index = _index(s)
        entry = index.find(account, allow_root=True)
        check = s.accounts.check_balance(entry.account.aid, statement_balance, as_of, days)
        if check is None:
            raise ToolError("account not found")

        def row(e) -> dict[str, Any]:
            return {
                "transaction_id": str(e.tid),
                "date": e.date.isoformat(),
                "payee": e.payee,
                "with": e.counter_accounts,
                "change": text(e.change),
            }

        return {
            "account": check.path,
            "account_id": str(check.aid),
            "as_of": check.as_of.isoformat(),
            "matches": check.matches,
            "book_balance": text(check.book_balance),
            "statement_balance": text(check.statement_balance),
            "difference": text(check.difference),
            "recent": [row(e) for e in check.recent],
            "same_size_as_difference": [row(e) for e in check.same_size_as_difference],
        }


@_tool_errors
def list_tags() -> dict[str, Any]:
    """The #hashtags the user has written in transaction notes (#reimbursable, #goa-trip), most used first, with how
    many entries carry each. To tag an entry, write the #tag in its note; find them with search_transactions(tag=)."""
    with services() as s:
        return {
            "tags": [
                {"tag": t.tag, "uses": t.uses, "last_used": t.last_used.isoformat()} for t in s.transactions.tags()
            ]
        }


@_tool_errors
def payee_defaults(
    payee: Annotated[str, Field(description="A payee or part of one; empty for the most used")] = "",
    limit: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict[str, Any]:
    """How the user usually books a payee: the accounts of their newest entry with that payee (from -> to), the kind
    (expense, income or transfer), how many times, and other routes seen. Use it to pick accounts the way the user
    does instead of guessing."""
    with services() as s:
        return {
            "payees": [
                {
                    "payee": d.payee,
                    "exact": d.exact,
                    "uses": d.uses,
                    "kind": d.kind,
                    "usually": {
                        "from": d.from_account.path,
                        "from_id": str(d.from_account.id),
                        "to": d.to_account.path,
                        "to_id": str(d.to_account.id),
                    },
                    "other_routes": [
                        {"from": o.from_account.path, "to": o.to_account.path, "uses": o.uses} for o in d.other_routes
                    ],
                }
                for d in s.transactions.payee_defaults(payee, limit)
            ]
        }


@_tool_errors
def get_transaction_history(
    transaction_id: Annotated[str, Field(description="Id from search_transactions or list_deleted_transactions")],
) -> dict[str, Any]:
    """Everything that happened to one transaction, oldest first: when it was made, each edit with exactly what
    changed (date, payee, note, reference, rows added, removed or changed) and who did it (web, api, import,
    recurring or an assistant), and its deletion. Works for a deleted transaction too."""
    tid = _transaction_id(transaction_id)
    with services() as s:
        steps = s.transactions.changes(tid)
        if not steps:
            raise ToolError("no history for that transaction: check the id")
        return {
            "transaction_id": str(tid),
            "exists": s.transactions.read(tid) is not None,
            "history": [_step(c, full=True) for c in steps],
        }


def _account_step(c: AccountChangeRead) -> dict[str, Any]:
    step: dict[str, Any] = {
        "at": c.at.isoformat(),
        "action": c.action,
        "by": _via(c.via),
        "account_id": str(c.account),
        "entry": _plain(c.entry),
    }
    if c.changes:
        step["changes"] = _plain(c.changes)
    return step


@_tool_errors
def get_account_history(
    account: Annotated[str, Field(description="Account path or id; the id for one that was deleted or merged away")],
) -> dict[str, Any]:
    """Everything that happened to one account or category, oldest first: when it was made, each rename, move,
    closing or reopening with what changed, who did it (web, api or an assistant), and its deletion if any.
    Changes made before finode kept this history are not listed."""
    with services() as s:
        index = _index(s)
        try:
            aid = index.find(account, allow_root=True).account.aid
        except ValueError:
            try:
                aid = UUID(account.strip())
            except ValueError:
                raise ToolError(
                    f"no account matches '{account}': use list_accounts, or the id of a deleted one!"
                ) from None
        steps = s.accounts.changes(aid)
        if not steps:
            raise ToolError("no history for that account: changes before finode kept one are not listed")
        return {
            "account_id": str(aid),
            "exists": aid in index.entries,
            "history": [_account_step(c) for c in steps],
        }


@_tool_errors
def recent_changes(
    since: Annotated[date | None, Field(description="From this day on (YYYY-MM-DD); no limit by default")] = None,
    by: Annotated[
        str | None,
        Field(
            description="Only changes made by: assistant (any), web, api, import, recurring, or mcp:<connection name>"
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    what: Annotated[
        Literal["transactions", "accounts"], Field(description="Changes to transactions, or to accounts")
    ] = "transactions",
) -> dict[str, Any]:
    """The latest changes across all transactions (or, with what='accounts', all accounts and categories), newest
    first: what was made, edited (with what changed) or deleted, when, and by whom. Use it to see what you or the
    user changed lately."""
    with services() as s:
        if what == "accounts":
            since_at = local_start_utc(since) if since else None
            changes = s.accounts.recent_changes(since_at, (by or "").strip() or None, limit)
            return {"changes": [_account_step(c) for c in changes], "count": len(changes), "limit": limit}
        steps = s.transactions.recent_changes(
            local_start_utc(since) if since else None, (by or "").strip() or None, limit
        )
        return {"changes": [_step(c, full=False) for c in steps], "count": len(steps), "limit": limit}


@_tool_errors
def spending_breakdown(
    kind: Annotated[Literal["expenses", "income"], Field(description="Expenses or income")] = "expenses",
    date_from: Annotated[date | None, Field(description="First day; the 1st of this month when left out")] = None,
    date_to: Annotated[date | None, Field(description="Last day; today when left out")] = None,
    depth: Annotated[int, Field(ge=1, le=2, description="1 = Food, Rent...; 2 = Food:Groceries...")] = 1,
) -> dict[str, Any]:
    """Expenses (or income) for a period per account, largest first."""
    with services() as s:
        report = s.reports.breakdown("Expenses" if kind == "expenses" else "Income", date_from, date_to, depth)
        return {
            "kind": kind,
            "currency": report.currency,
            "from": report.period_start.isoformat(),
            "to": report.period_end.isoformat(),
            "total": text(report.total),
            "by_account": [
                {"account": line.account.replace(" › ", ":"), "amount": text(line.amount)} for line in report.lines
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
                    **(
                        {
                            "postings": [
                                {"account": index.path(p.account), "side": p.side.value, "amount": text(p.amount)}
                                for p in r.postings
                            ],
                        }
                        if r.postings
                        else {
                            "from": index.path(cast(UUID, r.from_account)),
                            "to": index.path(cast(UUID, r.to_account)),
                            "amount": text(r.amount),
                        }
                    ),
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
    from_account: Annotated[
        str, Field(description="Where the money comes from, e.g. Assets:Bank:HDFC or Liabilities:Card")
    ],
    to_account: Annotated[str, Field(description="Where it goes, e.g. Expenses:Food")],
    date: OptionalDate = None,
    payee: Annotated[str | None, Field(max_length=40)] = None,
    note: Annotated[str | None, Field(max_length=200)] = None,
    related_to: Annotated[
        str | None,
        Field(
            description="Id of an earlier transaction this one is related to (a refund, a reversal); see search_transactions"
        ),
    ] = None,
    source: Source = None,
    external_id: ExternalId = None,
    source_url: SourceUrl = None,
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Record money moving from one account to another: spending, income or a transfer. When the entry comes from
    something outside finode (a bank message, a mail), pass its source and external_id: sending the same pair
    again is safe, it answers with the entry already recorded (`already_recorded`) and makes no copy."""
    with services() as s:
        index = _index(s)
        payer = index.find(from_account, postable=True)
        target = index.find(to_account, postable=True)
        postings = simple_postings(amount, payer.account.aid, target.account.aid)
        data = TransactionCreate(
            date=date or _today(),
            payee=(payee or "").strip() or None,
            comment=(note or "").strip() or None,
            postings=postings,
            related_id=_related_id(related_to),
            source=source,
            external_id=external_id,
            source_url=source_url,
        )
        if dry_run:
            return _dry_run("would_record", s.transactions.preview_create(data), index)
        saved, made = s.transactions.create_once(data)
        return _recorded(saved, made, index, s)


def _recorded(saved: TransactionRead, made: bool, index: AccountIndex, s: Services) -> dict[str, Any]:
    result: dict[str, Any] = {"recorded": _transaction(saved, index, s)}
    if not made:
        result["already_recorded"] = True
    return result


def _dry_run(key: str, preview: TransactionPreview, index: AccountIndex) -> dict[str, Any]:
    """What a dry run answers: the entry as it would be (or is) saved, marked as not saved."""
    debits = sum((p.amount for p in preview.postings if p.side == PostingSide.DEBIT), Decimal(0))
    entry: dict[str, Any] = {
        "id": str(preview.tid) if preview.tid else None,
        "date": preview.date.isoformat(),
        "payee": preview.payee,
        "note": preview.comment,
        "total": text(debits),
        "postings": [
            {
                "account": index.path(p.account),
                "account_id": str(p.account),
                "side": p.side.value,
                "amount": text(p.amount),
            }
            for p in preview.postings
        ],
        "related_to": str(preview.related_id) if preview.related_id else None,
        "reference": {"source": preview.source, "external_id": preview.external_id, "url": preview.source_url}
        if preview.source or preview.external_id or preview.source_url
        else None,
    }
    result: dict[str, Any] = {"dry_run": True, "saved": False, key: entry}
    if preview.already_recorded:
        result["already_recorded"] = str(preview.already_recorded)
    return result


class PostingIn(BaseModel):
    account: AccountRef
    side: Literal["debit", "credit"] = Field(
        description="debit: money into an asset or expense (or paying down a liability); credit: the other way"
    )
    amount: Amount


def _postings(index: AccountIndex, rows: list[PostingIn]) -> list[PostingCreate]:
    return [
        PostingCreate(
            account=index.find(row.account, postable=True).account.aid,
            side=PostingSide(row.side),
            amount=row.amount,
        )
        for row in rows
    ]


@_tool_errors
def record_split(
    postings: Annotated[list[PostingIn], Field(min_length=2, description="Debits and credits; they must balance")],
    date: OptionalDate = None,
    payee: Annotated[str | None, Field(max_length=40)] = None,
    note: Annotated[str | None, Field(max_length=200)] = None,
    related_to: Annotated[
        str | None,
        Field(
            description="Id of an earlier transaction this one is related to (a refund, a reversal); see search_transactions"
        ),
    ] = None,
    source: Source = None,
    external_id: ExternalId = None,
    source_url: SourceUrl = None,
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Record a transaction with several rows, e.g. a bill split across categories or a salary
    with deductions. Debits must equal credits. source and external_id work as for record_transaction."""
    with services() as s:
        index = _index(s)
        data = TransactionCreate(
            date=date or _today(),
            payee=(payee or "").strip() or None,
            comment=(note or "").strip() or None,
            postings=_postings(index, postings),
            related_id=_related_id(related_to),
            source=source,
            external_id=external_id,
            source_url=source_url,
        )
        if dry_run:
            return _dry_run("would_record", s.transactions.preview_create(data), index)
        saved, made = s.transactions.create_once(data)
        return _recorded(saved, made, index, s)


class BatchItem(BaseModel):
    """One entry of record_transactions: either amount, from_account and to_account, or postings."""

    amount: Amount | None = None
    from_account: AccountRef | None = None
    to_account: AccountRef | None = None
    postings: list[PostingIn] | None = Field(default=None, description="For a split, instead of amount/from/to")
    date: OptionalDate = None
    payee: Annotated[str | None, Field(max_length=40)] = None
    note: Annotated[str | None, Field(max_length=200)] = None
    related_to: str | None = Field(default=None, description="Id of an earlier transaction this one is related to")
    source: Source = None
    external_id: ExternalId = None
    source_url: SourceUrl = None


@_tool_errors
def record_transactions(
    entries: Annotated[
        list[BatchItem],
        Field(min_length=1, max_length=MAX_BATCH, description="Up to 50 entries; each is a simple one or a split"),
    ],
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Record several transactions as one: all are saved or none (one approval, one check). Give each entry a
    source and external_id so the batch can be sent again safely: entries already recorded are skipped
    (`already_recorded`). Any problem refuses the whole batch and names the entries at fault by their number
    (1 is the first)."""
    with services() as s:
        index = _index(s)
        data: list[TransactionCreate] = []
        problems: list[str] = []
        for number, e in enumerate(entries, start=1):
            try:
                data.append(_batch_entry(e, index))
            except (ValueError, LookupError, ValidationError) as err:
                message = validation_message(err) if isinstance(err, ValidationError) else str(err)
                problems.append(f"entry {number}: {message}")
        if problems:
            raise ToolError("nothing was saved. " + " ".join(problems))
        result = s.transactions.record_batch(data, dry_run)
        out: list[dict[str, Any]] = []
        for r in result.entries:
            if isinstance(r.transaction, TransactionPreview):
                shown = _dry_run("entry", r.transaction, index)["entry"]
            else:
                shown = _transaction(r.transaction, index, s)
            out.append({"entry": r.item, "status": r.status, "transaction": shown})
        return {
            "dry_run": result.dry_run,
            "saved": result.saved,
            "recorded": result.created,
            "already_recorded": result.already_recorded,
            "entries": out,
        }


def _batch_entry(e: BatchItem, index: AccountIndex) -> TransactionCreate:
    simple = (e.amount, e.from_account, e.to_account)
    if e.postings is not None:
        if any(v is not None for v in simple):
            raise ValueError("give either amount, from_account and to_account, or postings, not both!")
        postings = _postings(index, e.postings)
    else:
        if any(v is None for v in simple):
            raise ValueError("give amount, from_account and to_account, or postings!")
        payer = index.find(cast(str, e.from_account), postable=True)
        target = index.find(cast(str, e.to_account), postable=True)
        postings = simple_postings(cast(Decimal, e.amount), payer.account.aid, target.account.aid)
    return TransactionCreate(
        date=e.date or _today(),
        payee=(e.payee or "").strip() or None,
        comment=(e.note or "").strip() or None,
        postings=postings,
        related_id=_related_id(e.related_to),
        source=e.source,
        external_id=e.external_id,
        source_url=e.source_url,
    )


@_tool_errors
def update_transaction(
    transaction_id: Annotated[str, Field(description="Id from search_transactions")],
    date: Annotated[date | None, Field(description="New date (YYYY-MM-DD)")] = None,
    payee: Annotated[str | None, Field(max_length=40, description="New payee; an empty string clears it")] = None,
    note: Annotated[str | None, Field(max_length=200, description="New note; an empty string clears it")] = None,
    postings: Annotated[
        list[PostingIn] | None, Field(description="All the rows again, replacing the old ones; leave out to keep them")
    ] = None,
    related_to: Annotated[
        str | None,
        Field(description="Id of an earlier transaction this one is related to; an empty string removes the link"),
    ] = None,
    source: Annotated[Source, Field(description="New source; an empty string clears it")] = None,
    external_id: Annotated[
        ExternalId, Field(description="New reference (needs a source); an empty string clears it")
    ] = None,
    source_url: Annotated[SourceUrl, Field(description="New link; an empty string clears it")] = None,
    dry_run: DryRun = False,
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
        if related_to is not None:
            changes["related_id"] = _related_id(related_to)
        for key, value in (("source", source), ("external_id", external_id), ("source_url", source_url)):
            if value is not None:
                changes[key] = value
        if not changes:
            raise ToolError(
                "nothing to change: pass a date, payee, note, postings, related_to, source, external_id or source_url!"
            )
        if dry_run:
            return _dry_run("would_become", s.transactions.preview_update(tid, TransactionUpdate(**changes)), index)
        saved = s.transactions.update(tid, TransactionUpdate(**changes))
        if saved is None:
            raise ToolError("transaction not found")
        return {"updated": _transaction(saved, index, s)}


@_tool_errors
def delete_transaction(
    transaction_id: Annotated[str, Field(description="Id from search_transactions")],
    dry_run: DryRun = False,
) -> dict[str, Any]:
    """Delete a transaction (it waits in the user's recently deleted list and can be restored). Ask the user to confirm first."""
    tid = _transaction_id(transaction_id)
    with services() as s:
        index = _index(s)
        if dry_run:
            return _dry_run("would_delete", s.transactions.preview_delete(tid), index)
        existing = s.transactions.read(tid)
        if existing is None:
            raise ToolError("transaction not found")
        s.transactions.delete(tid)
        return {"deleted": _transaction(existing, index, s)}


@_tool_errors
def create_account(
    name: Annotated[str, Field(max_length=40, description="The new account's own name, without ':'")],
    parent: Annotated[str, Field(description="Where it goes, e.g. Expenses or Assets:Bank")],
    opening_balance: Annotated[
        Decimal | None, Field(ge=0, description="Assets and liabilities only: what it holds (or owes) today")
    ] = None,
    details: Annotated[str | None, Field(max_length=200, description="What the account is for, in a few words")] = None,
    on_budget: Annotated[
        bool | None, Field(description="Assets and liabilities: whether the money is part of the budget")
    ] = None,
    payment_category: Annotated[
        str | None, Field(description="An account outside the budget: the expense category its payments count under")
    ] = None,
) -> dict[str, Any]:
    """Add an account. Check list_accounts first so you don't create a duplicate."""
    with services() as s:
        index = _index(s)
        parent_entry = index.find(parent, allow_root=True)
        name = name.strip()
        siblings = [e for e in index.entries.values() if e.account.parent_id == parent_entry.account.aid]
        twin = next((e for e in siblings if e.account.name.casefold() == name.casefold()), None)
        if twin:
            raise ToolError(
                f"'{parent_entry.path}' already has an account named '{twin.account.name}': use {twin.path}!"
            )
        if opening_balance and parent_entry.root not in ("Assets", "Liabilities"):
            raise ToolError("only asset and liability accounts have an opening balance!")
        created = s.accounts.create(
            AccountCreate(
                name=name,
                details=(details or "").strip() or None,
                parent_id=parent_entry.account.aid,
                balance=opening_balance or Decimal("0.00"),
                on_budget=on_budget,
                payment_category_id=_category(index, payment_category).account.aid if payment_category else None,
            )
        )
        return {
            "created": {
                "id": str(created.aid),
                "path": f"{parent_entry.path}:{created.name}",
                "balance": text(created.balance),
            }
        }


@_tool_errors
def create_recurring(
    amount: Annotated[
        Amount | None,
        Field(description="How much leaves the 'from' account each time (a simple rule; not with postings)"),
    ] = None,
    from_account: Annotated[AccountRef | None, Field(description="A simple rule: where the money comes from")] = None,
    to_account: Annotated[AccountRef | None, Field(description="A simple rule: where it goes")] = None,
    frequency: Annotated[
        Literal["daily", "weekly", "monthly", "yearly"], Field(description="The unit between occurrences")
    ] = "monthly",
    every: Annotated[int, Field(ge=1, le=366, description="Every N units: 2 with weekly is fortnightly")] = 1,
    start_date: Annotated[
        date | None,
        Field(description="First occurrence, YYYY-MM-DD; today when left out. Past dates are recorded right away"),
    ] = None,
    end_date: Annotated[date | None, Field(description="Last possible occurrence; none when left out")] = None,
    payee: Annotated[str | None, Field(max_length=40)] = None,
    note: Annotated[str | None, Field(max_length=200)] = None,
    postings: Annotated[
        list[PostingIn] | None,
        Field(
            min_length=2,
            description="Instead of from, to and amount: a split over several accounts, like record_split (debits must equal credits)",
        ),
    ] = None,
) -> dict[str, Any]:
    """Set up a transaction that finode records by itself on a schedule (rent, salary, a subscription).
    Give from_account, to_account and amount for a simple one, or postings for a split (a salary with
    deductions, a bill over several categories). Check list_recurring first so you don't create a duplicate."""
    with services() as s:
        index = _index(s)
        if postings:
            if any(v is not None for v in (amount, from_account, to_account)):
                raise ToolError("give either from_account, to_account and amount, or postings, not both!")
            source = target = None
            shape: dict[str, Any] = {
                "postings": [
                    p.model_dump() | {"account": index.find(p.account, postable=True).account.aid} for p in postings
                ]
            }
        else:
            if amount is None or from_account is None or to_account is None:
                raise ToolError("give from_account, to_account and amount, or postings!")
            source = index.find(from_account, postable=True)
            target = index.find(to_account, postable=True)
            shape = {"from_account": source.account.aid, "to_account": target.account.aid, "amount": amount}
        created = s.recurring.create(
            RecurringCreate(
                **shape,
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
        if rule is None:
            raise ToolError("the recurring transaction was not saved")
        what = (
            {"from": source.path, "to": target.path, "amount": text(rule.amount)}
            if source is not None and target is not None
            else {
                "postings": [
                    {"account": index.path(p.account), "side": p.side.value, "amount": text(p.amount)}
                    for p in rule.postings
                ]
            }
        )
        return {
            "created": {
                "id": str(rule.rid),
                **what,
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
            raise ToolError(
                f"'{recurring_id}' is not a recurring transaction id: use the id from list_recurring!"
            ) from None
        rule = s.recurring.set_active(rid, False)
        if rule is None:
            raise ToolError("no recurring transaction has that id!")
        return {"paused": str(rule.rid)}


@_tool_errors
def skip_recurring_occurrence(
    recurring_id: Annotated[str, Field(description="The id from list_recurring")],
) -> dict[str, Any]:
    """Leave out the next occurrence of a running recurring transaction (a month without the subscription):
    nothing is recorded for it and the rule carries on with the one after. Only when the user asks."""
    with services() as s:
        try:
            rid = UUID(recurring_id.strip())
        except ValueError:
            raise ToolError(
                f"'{recurring_id}' is not a recurring transaction id: use the id from list_recurring!"
            ) from None
        before = s.recurring.read(rid)
        if before is None:
            raise ToolError("no recurring transaction has that id!")
        rule = s.recurring.skip_next(rid)
        if rule is None:
            raise ToolError("no recurring transaction has that id!")
        return {
            "skipped": before.next_date.isoformat(),
            "next_due": rule.next_date.isoformat() if rule.active else None,
        }


def _today() -> date:
    return local_today()


# ---- prompts ---------------------------------------------------------------------------------------


def monthly_review(month: Annotated[str | None, Field(description="YYYY-MM; this month when left out")] = None) -> str:
    """Review a month: where the money went and how net worth moved."""
    period = f"the month {month}" if month else "this month so far"
    return (
        f"Give me a short review of {period} in finode. Use get_overview for net worth, "
        "spending_breakdown for expenses and income by account (compare with the month before), "
        "and search_transactions for the largest expenses. Point out anything unusual. Keep it brief."
    )


def _month(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value + "-01") if len(value.strip()) == 7 else date.fromisoformat(value.strip())
    except ValueError:
        raise ToolError(f"'{value}' is not a month: use YYYY-MM!") from None


def _category(index: AccountIndex, text: str):
    entry = index.find(text)
    if entry.root != "Expenses" or entry.account.parent_id is None:
        raise ToolError(f"'{entry.path}' is not an expense account: budget categories are expense accounts!")
    return entry


def _budget(data) -> dict[str, Any]:
    return {
        "month": data.month.strftime("%Y-%m"),
        "currency": data.currency,
        "ready_to_assign": text(data.ready_to_assign),
        "assigned_this_month": text(data.assigned),
        "spent_this_month": text(data.activity),
        "available_total": text(data.available),
        **({"assigned_to_later_months": text(data.assigned_to_later_months)} if data.assigned_to_later_months else {}),
        **(
            {
                "money_in_accounts": text(data.money_in_accounts),
                "reserved_for_card_bills": text(data.reserved_for_cards),
                "credit_cards": [
                    {
                        "card_id": str(c.aid),
                        "card": c.path,
                        "to_pay": text(c.owed),
                        "charged_this_month": text(c.charged),
                        "paid_this_month": text(c.paid),
                    }
                    for c in data.cards
                ],
            }
            if data.cards
            else {}
        ),
        "overspent_last_month": text(data.overspent_last_month),
        "budget_accounts": data.budget_accounts,
        **(
            {
                "saved_for_goals": text(data.goal_available),
                "goals": [
                    {
                        "goal_id": str(g.gid),
                        "goal": g.name,
                        "saved": text(g.available),
                        "target": text(g.amount),
                        "by": g.target_date.isoformat(),
                        "assigned_this_month": text(g.assigned),
                        **({"needs_this_month": text(g.underfunded)} if g.underfunded else {}),
                    }
                    for g in data.goals
                ],
            }
            if data.goals
            else {}
        ),
        "categories": [
            {
                "category_id": str(line.aid),
                "category": line.path,
                "is_group": line.group,
                "assigned": text(line.assigned),
                "spent": text(line.activity),
                "available": text(line.available),
                **({"overspent_last_month": text(line.overspent_last_month)} if line.overspent_last_month else {}),
            }
            for line in data.lines
        ],
        **(
            {
                "note_left_out": f"{text(data.left_out)} spent this month was paid from accounts outside the budget and is not counted: "
                + ", ".join(a.path for a in data.left_out_accounts)
                + ". The user can switch 'Part of the budget' on for them."
            }
            if data.left_out_accounts
            else {}
        ),
        **(
            {
                "note_accounts": "No account is part of the budget yet: the user switches 'Part of the budget' on for an account."
            }
            if not data.budget_accounts
            else {}
        ),
    }


@_tool_errors
def get_budget(
    month: Annotated[str | None, Field(description="YYYY-MM; this month by default")] = None,
) -> dict[str, Any]:
    """The envelope budget for a month: what is still ready to assign, and for each expense category what
    was assigned this month, what was spent and what is available (leftovers carry over; a category overspent last month starts at zero and that amount was already taken out of ready to assign).
    Groups sum their subcategories."""
    with services() as s:
        return _budget(s.budget.view(_month(month)))


@_tool_errors
def assign_to_category(
    category: Annotated[str, Field(description="An expense account, e.g. Groceries or Expenses:Food:Groceries")],
    amount: Annotated[
        Decimal, Field(ge=0, description="The month's total for the category (replaces what was assigned; 0 clears it)")
    ],
    month: Annotated[str | None, Field(description="YYYY-MM; this month by default")] = None,
) -> dict[str, Any]:
    """Give money a job: set how much of a month is assigned to a category. This is a plan only; no transaction
    is recorded. Check get_budget first so you don't assign more than is ready to assign."""
    with services() as s:
        entry = _category(_index(s), category)
        return _budget(s.budget.assign(_month(month), entry.account.aid, amount))


def _goal(s, name: str):
    """The goal called `name` (capitals aside), or an explanation of the ones there are."""
    goals = s.budget.view(None).goals
    for goal in goals:
        if goal.name.lower() == name.strip().lower():
            return goal
    raise ValueError(f"no goal is called '{name}'. Goals: {', '.join(g.name for g in goals) or 'none yet'}.")


@_tool_errors
def assign_to_goal(
    goal: Annotated[str, Field(description="The goal's name, e.g. Emergency fund (see `goals` in get_budget)")],
    amount: Annotated[
        Decimal,
        Field(
            description="The month's total set aside for the goal (replaces it; 0 clears it; negative takes back what was saved before)"
        ),
    ],
    month: Annotated[str | None, Field(description="YYYY-MM; this month by default")] = None,
) -> dict[str, Any]:
    """Set money aside for a goal in a month. This is a plan only; no transaction is recorded. It lowers what is
    ready to assign, so check get_budget first."""
    with services() as s:
        return _budget(s.budget.assign_goal(_month(month), _goal(s, goal).gid, amount))


@_tool_errors
def use_goal(
    goal: Annotated[str, Field(description="The goal whose saved money is used")],
    category: Annotated[str, Field(description="The expense category that paid for the thing, e.g. Health:Hospital")],
    amount: Annotated[Decimal, Field(gt=0, description="At most what is saved in the goal")],
    month: Annotated[str | None, Field(description="YYYY-MM; this month by default")] = None,
) -> dict[str, Any]:
    """Hand money a goal saved to a category, so spending recorded there is covered. It does not change what is
    ready to assign."""
    with services() as s:
        entry = _category(_index(s), category)
        return _budget(s.budget.use_goal(_month(month), _goal(s, goal).gid, entry.account.aid, amount))


@_tool_errors
def copy_budget_from_previous_month(
    month: Annotated[str | None, Field(description="The month to fill, YYYY-MM; this month by default")] = None,
) -> dict[str, Any]:
    """Assign a month what each category got the month before, for categories with nothing assigned yet
    (nothing is overwritten). A quick way to start a month; check get_budget afterwards."""
    with services() as s:
        return _budget(s.budget.copy_previous(_month(month)))


@_tool_errors
def move_budget_money(
    from_category: Annotated[str, Field(description="The expense category the money is available in")],
    to_category: Annotated[str, Field(description="The expense category that should get it")],
    amount: Annotated[Decimal, Field(gt=0, description="At most what is available in the first category")],
    month: Annotated[str | None, Field(description="YYYY-MM; this month by default")] = None,
) -> dict[str, Any]:
    """Move assigned money from one category to another. It does not change what is ready to assign."""
    with services() as s:
        index = _index(s)
        source, target = _category(index, from_category), _category(index, to_category)
        return _budget(s.budget.move(_month(month), source.account.aid, target.account.aid, amount))


@_tool_errors
def get_status() -> dict[str, Any]:
    """What this connection is and may do: its access level, the user's currency and today's date, how much
    is in the books, when they last changed and how much room is left. Call it first when unsure."""
    with services() as s:
        owner = s.owner
        used = s.transactions.recorded_today()
        per_day = settings.max_transactions_per_day
        last = s.transactions.last_change()
        return {
            "app_version": VERSION,
            "connection": {
                "name": owner.name,
                "access": TokenScope.LABELS.get(owner.scope, owner.scope),
                "can_change_things": TokenScope.can_write(owner.scope),
                "can_change_accounts": TokenScope.can_manage(owner.scope),
            },
            "currency": s.accounts.currency().code,
            "today": _today().isoformat(),
            "books": {
                "accounts": len(s.accounts.list()),
                "transactions": s.transactions.count(),
                "last_change": last.isoformat() if last else None,
            },
            "limits": {
                "accounts": settings.max_accounts or None,
                "transactions": settings.max_transactions or None,
                "new_transactions_per_day": per_day or None,
                "new_transactions_left_today": max(per_day - used, 0) if per_day else None,
                "postings_per_transaction": settings.max_postings_per_transaction or None,
            },
        }


@_tool_errors
def check_books(as_of: str | None = None) -> dict[str, Any]:
    """Check that the books are sound: debits equal credits in every transaction and overall.
    Returns the trial balance (debits and credits per account) and any problems found.
    as_of: a day (YYYY-MM-DD), today by default."""
    try:
        day = date.fromisoformat(as_of) if as_of else None
    except ValueError:
        raise ToolError(f"'{as_of}' is not a date: use YYYY-MM-DD!") from None
    with services() as s:
        trial = s.reports.trial_balance(day)
        return {
            "as_of": trial.as_of.isoformat(),
            "balanced": trial.balanced,
            "problems": trial.problems,
            "currency": trial.currency,
            "total_debit": text(trial.debit),
            "total_credit": text(trial.credit),
            "accounts": [
                {"account": line.account, "debit": text(line.debit), "credit": text(line.credit)}
                for line in trial.lines
            ],
        }


@_tool_errors
def list_deleted_transactions() -> dict[str, Any]:
    """Transactions that were deleted and can still be brought back, newest deletion first (up to 50). Use the
    `deleted_id` with restore_transaction."""
    with services() as s:
        rows = []
        for h in s.transactions.restorable():
            total = sum((p.amount for p in h.postings if p.side == PostingSide.DEBIT), Decimal(0))
            rows.append(
                {
                    "deleted_id": str(h.hid),
                    "transaction_id": str(h.transaction),
                    "deleted_at": h.at.isoformat(),
                    "date": h.date.isoformat(),
                    "payee": h.payee,
                    "note": h.comment,
                    "total": text(total),
                }
            )
        return {"deleted": rows}


@_tool_errors
def restore_transaction(
    deleted_id: Annotated[str, Field(description="The deleted_id from list_deleted_transactions")],
) -> dict[str, Any]:
    """Bring a deleted transaction back as it was. It returns as an ordinary entry (a link to a recurring rule or to a
    related entry is not restored)."""
    try:
        hid = UUID(deleted_id.strip())
    except ValueError:
        raise ToolError(
            f"'{deleted_id}' is not a deleted-transaction id: use the deleted_id from list_deleted_transactions!"
        ) from None
    with services() as s:
        try:
            restored = s.transactions.restore(hid)
        except LookupError:
            raise ToolError("no deleted transaction has that id!") from None
        return {"restored": _transaction(restored, _index(s), s)}


@_tool_errors
def resume_recurring(
    recurring_id: Annotated[str, Field(description="The id from list_recurring")],
) -> dict[str, Any]:
    """Resume a paused recurring transaction. What fell due while it was paused is not recorded late; it carries on
    from the next occurrence."""
    with services() as s:
        try:
            rid = UUID(recurring_id.strip())
        except ValueError:
            raise ToolError(
                f"'{recurring_id}' is not a recurring transaction id: use the id from list_recurring!"
            ) from None
        rule = s.recurring.set_active(rid, True)
        if rule is None:
            raise ToolError("no recurring transaction has that id!")
        return {"resumed": str(rule.rid), "next_due": rule.next_date.isoformat() if rule.active else None}


def _goal_month(value: str) -> date:
    month = _month(value)
    if month is None:
        raise ToolError("pass the month the goal is needed by, YYYY-MM!")
    return month


@_tool_errors
def create_goal(
    name: Annotated[str, Field(description="What it is for, e.g. Emergency fund (at most 80 characters)")],
    amount: Annotated[Decimal, Field(gt=0, description="How much to save in all")],
    by: Annotated[str, Field(description="The month it is needed by, YYYY-MM; after this month")],
    set_aside_now: Annotated[
        bool, Field(description="Also set aside this month's share (it lowers ready to assign)")
    ] = False,
) -> dict[str, Any]:
    """Create a savings goal. Goals are listed under `goals` in get_budget."""
    with services() as s:
        return _budget(s.budget.create_goal(name, amount, _goal_month(by), set_aside_now))


@_tool_errors
def update_goal(
    goal: Annotated[str, Field(description="The goal's current name")],
    name: Annotated[str | None, Field(description="New name; leave out to keep it")] = None,
    amount: Annotated[Decimal | None, Field(gt=0, description="New target amount; leave out to keep it")] = None,
    by: Annotated[str | None, Field(description="New month it is needed by, YYYY-MM; leave out to keep it")] = None,
) -> dict[str, Any]:
    """Change a goal's name, target amount or month. What is saved in it stays."""
    with services() as s:
        current = _goal(s, goal)
        if name is None and amount is None and by is None:
            raise ToolError("nothing to change: pass a name, amount or by!")
        return _budget(
            s.budget.update_goal(
                current.gid,
                name if name is not None else current.name,
                amount if amount is not None else current.amount,
                _goal_month(by) if by else current.target_date,
            )
        )


@_tool_errors
def delete_goal(goal: Annotated[str, Field(description="The goal's name")]) -> dict[str, Any]:
    """Delete a goal for good: what was saved in it goes back to ready to assign. Ask the user to confirm first."""
    with services() as s:
        found = _goal(s, goal)
        s.budget.delete_goal(found.gid)
        return {"deleted": found.name, "returned_to_ready_to_assign": text(found.available)}


# Changing accounts: only on a connection allowed to manage them (the others list these tools but they refuse).
MANAGE_TOOLS: list[tuple[Callable, ToolAnnotations]] = []

READ_TOOLS = [
    get_status,
    get_overview,
    list_accounts,
    get_account,
    search_transactions,
    get_transaction,
    get_transaction_history,
    get_account_history,
    recent_changes,
    list_tags,
    payee_defaults,
    check_balance,
    spending_breakdown,
    list_recurring,
    check_books,
    get_budget,
    list_deleted_transactions,
]
WRITE_TOOLS = [
    (record_transaction, WRITE),
    (record_split, WRITE),
    (record_transactions, WRITE),
    (update_transaction, IDEMPOTENT_WRITE),
    (delete_transaction, DESTRUCTIVE),
    (create_account, WRITE),
    (create_recurring, WRITE),
    (stop_recurring, IDEMPOTENT_WRITE),
    (skip_recurring_occurrence, WRITE),
    (resume_recurring, IDEMPOTENT_WRITE),
    (restore_transaction, WRITE),
    (create_goal, WRITE),
    (update_goal, IDEMPOTENT_WRITE),
    (delete_goal, DESTRUCTIVE),
    (assign_to_category, IDEMPOTENT_WRITE),
    (assign_to_goal, IDEMPOTENT_WRITE),
    (use_goal, WRITE),
    (move_budget_money, WRITE),
    (copy_budget_from_previous_month, IDEMPOTENT_WRITE),
]


READ_ONLY_MESSAGE = (
    "This connection is read-only, so nothing was changed. The user can allow changes in finode under "
    "Profile > AI assistants (Change access), and then you can try again."
)
NO_MANAGE_MESSAGE = (
    "This connection may record and change transactions but not change accounts, so nothing was changed. The user "
    "can allow it in finode under Profile > AI assistants (Change access, read, write & manage accounts), and then "
    "you can try again."
)
NO_MANAGE_NOTE = (
    "\nThis connection can change transactions but not accounts: the tools that rename, move, close, reopen or merge "
    "accounts are listed but always refuse. If the user asks for that, say so and tell them to allow account changes "
    "in finode under Profile > AI assistants.\n"
)
MANAGE_NOTE = (
    "\nThis connection may also change accounts (rename, move, close, reopen and merge them), but never delete them. "
    "These changes affect how the user's whole history is organised: say what you will do and get the user's go-ahead "
    "first, and use dry_run where a tool has it.\n"
)
READ_ONLY_NOTE = (
    "\nThis connection is read-only: the tools that change things are listed but always refuse (except with "
    "dry_run=true, which only checks). If the user asks for a change, say so and tell them to allow read & write "
    "access in finode under Profile > AI assistants.\n"
)


def _refused(fn: Callable, message: str = READ_ONLY_MESSAGE, why: str = "this connection is read-only") -> Callable:
    """The same tool for a connection that may not use it: it keeps its name and arguments but only explains."""

    @wraps(fn)
    def refuse(*args, **kwargs):
        if kwargs.get("dry_run") is True:
            return fn(*args, **kwargs)  # only checks: nothing is changed, so a connection may always ask
        raise ToolError(message)

    summary = (fn.__doc__ or fn.__name__).strip().splitlines()[0]
    can_check = "dry_run" in fn.__annotations__
    refuse.__doc__ = (
        f"Unavailable: {why}{' (dry_run=true still works)' if can_check else ''}. (Would otherwise: {summary})"
    )
    return refuse


def build_server(access: str = TokenScope.WRITE) -> MCPServer:
    """The server for one access level: read, write, or manage (write and changing accounts)."""
    notes = {TokenScope.READ: READ_ONLY_NOTE, TokenScope.WRITE: NO_MANAGE_NOTE, TokenScope.MANAGE: MANAGE_NOTE}
    server = MCPServer(
        name="finode",
        title="finode",
        instructions=INSTRUCTIONS + notes[access],
        website_url="https://finode.bijesh.me",
    )
    for fn in READ_TOOLS:
        server.add_tool(fn, annotations=READ)
    for fn, annotations in WRITE_TOOLS:
        server.add_tool(fn if TokenScope.can_write(access) else _refused(fn), annotations=annotations)
    for fn, annotations in MANAGE_TOOLS:
        if TokenScope.can_manage(access):
            server.add_tool(fn, annotations=annotations)
        else:
            refused = READ_ONLY_MESSAGE if access == TokenScope.READ else NO_MANAGE_MESSAGE
            why = (
                "this connection is read-only"
                if access == TokenScope.READ
                else "this connection may not change accounts"
            )
            server.add_tool(_refused(fn, refused, why), annotations=annotations)
    server.prompt()(monthly_review)
    return server
