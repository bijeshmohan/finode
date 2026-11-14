"""JSON API for the finode app's screens (`/api/views`): one call answers what one screen shows, built from the same
rows as the web pages (services/transaction_rows.py), so the app works out nothing the server already knows."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_authenticated_user
from ..clock import local_today
from ..dependencies import Accounts, Budget, Categories, Contacts, Recurring, Reports, Transactions
from ..schemas.views import (
    AppliedFilter,
    DayTotal,
    FilterChoice,
    FilterOptions,
    FilterSummary,
    GlanceRead,
    HomeView,
    LineRead,
    PersonRef,
    RowRead,
    StepRead,
    TransactionDetails,
    TransactionsView,
    UpcomingRead,
)
from ..services.home import home_view
from ..services.transaction_rows import (
    PAGE_SIZE,
    AccountIndex,
    ListFilters,
    TransactionRow,
    day_totals,
    filter_options,
    month_list,
    transaction_details,
)

router = APIRouter(prefix="/views", tags=["views"], dependencies=[Depends(require_authenticated_user)])


def parse_month(month: str, today: date) -> date:
    """The first of a `YYYY-MM` month, never one that has not started (this month for anything else)."""
    this_month = today.replace(day=1)
    try:
        when = date.fromisoformat(f"{month}-01") if month else this_month
    except ValueError:
        when = this_month
    return min(when, this_month)


def row_read(row: TransactionRow) -> RowRead:
    t = row.transaction
    return RowRead(
        id=t.id,
        date=t.date,
        title=row.title,
        sub=row.sub,
        amount=row.amount,
        kind=row.kind,
        is_system=row.is_system,
        is_opening=row.is_opening,
        related=row.related,
        recurring=row.recurring,
        by_assistant=row.by_assistant,
    )


def days_of(rows: list[TransactionRow]) -> list[DayTotal]:
    return [DayTotal(date=day, spent=spent) for day, spent in day_totals(rows).items()]


def _index(accounts: Accounts, categories: Categories) -> AccountIndex:
    return AccountIndex.build(accounts.list(), categories.list(include_closed=True))


@router.get("/transactions", response_model=TransactionsView)
def transactions_view(
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    recurring: Recurring,
    month: str = "",
    account: str = "",
    category: str = "",
    merchant: str = "",
    tag: str = "",
    q: str = "",
    kind: str = "",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=PAGE_SIZE, ge=1, le=100),
):
    """A page of one month's entries for the Transactions screen, newest first up to today (a day is never split between
    pages: the next page starts at `offset + len(rows)`). With an account, category, merchant or tag filter, `summary`
    adds up everything that matches; on the first page of the current month, `upcoming` lists what is dated ahead."""
    recurring.catch_up()  # record what has fallen due, as the pages do
    today = local_today()
    filters = ListFilters(account, category, merchant, tag, q, kind)
    found = month_list(
        transactions, _index(accounts, categories), parse_month(month, today), today, filters, offset, limit
    )
    return TransactionsView(
        month=found.when.strftime("%Y-%m"),
        is_current=found.is_current,
        rows=[row_read(r) for r in found.rows],
        days=days_of(found.rows),
        total=found.total,
        summary=FilterSummary(count=found.summary.count, total=found.summary.total, word=found.summary.word)
        if found.summary
        else None,
        upcoming=[
            UpcomingRead(id=u.transaction_id, date=u.date, title=u.title, sub=u.sub, amount=u.amount, income=u.income)
            for u in found.upcoming
        ],
        upcoming_total=found.upcoming_total,
        error=found.error,
        applied=[AppliedFilter(key=a.key, label=a.label, name=a.name) for a in found.applied],
    )


@router.get("/transaction-filters", response_model=FilterOptions)
def transaction_filters(accounts: Accounts, categories: Categories, transactions: Transactions):
    """The choices behind the Transactions screen's Filter sheet: accounts, categories (with their parent) and payees."""
    found = filter_options(accounts.list(), categories.list(include_closed=True), transactions)
    return FilterOptions(
        accounts=[FilterChoice(**a) for a in found["accounts"]],
        categories=[FilterChoice(**c) for c in found["categories"]],
        merchants=found["merchants"],
    )


@router.get("/transactions/{transaction_id}", response_model=TransactionDetails)
def transaction_view(
    transaction_id: UUID, accounts: Accounts, categories: Categories, transactions: Transactions, contacts: Contacts
):
    """One entry as its details sheet shows it."""
    found = transaction_details(transaction_id, transactions, contacts, _index(accounts, categories))
    if found is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    t = found.row.transaction
    return TransactionDetails(
        row=row_read(found.row),
        from_label=found.from_label,
        to_label=found.to_label,
        from_lines=[
            LineRead(name=line.name, amount=line.amount, posted_on=line.posted_on) for line in found.from_lines
        ],
        to_lines=[LineRead(name=line.name, amount=line.amount, posted_on=line.posted_on) for line in found.to_lines],
        comment=t.comment,
        tags=list(t.tags or []),
        related_to=row_read(found.related_to) if found.related_to else None,
        related=[row_read(r) for r in found.related],
        person=PersonRef(id=found.person_id, name=found.person_name) if found.person_id and found.person_name else None,
        loan_like=found.loan_like,
        with_names=found.with_names,
        source=t.source,
        source_url=t.source_url,
        external_id=t.external_id,
        added_by=found.added_by,
        changed_by=found.changed_by,
    )


@router.get("/home", response_model=HomeView)
def home(
    accounts: Accounts,
    categories: Categories,
    reports: Reports,
    transactions: Transactions,
    recurring: Recurring,
    budget: Budget,
    month: str = "",
):
    """Home for a month (`YYYY-MM`, never ahead): the budget at a glance, the month's first entries (a day is never cut;
    the rest come from `/views/transactions`), and a new person's first steps while some are left."""
    recurring.catch_up()  # record what has fallen due, as the page does
    found = home_view(parse_month(month, local_today()), accounts, categories, reports, transactions, budget)
    g = found.glance
    return HomeView(
        month=found.when.strftime("%Y-%m"),
        is_current=found.is_current,
        has_recorded=found.has_recorded,
        glance=GlanceRead(
            has_budget=g.has_budget,
            left=g.left,
            spent=g.spent,
            assigned=g.assigned,
            carried=g.carried,
            of=g.of,
            percent=g.percent,
            pace=g.pace,
        ),
        spent=found.summary.spent,
        steps=[StepRead(key=s.key, title=s.title, done=s.done, hint=s.hint) for s in found.steps]
        if found.steps_left
        else None,
        steps_done=sum(1 for s in found.steps if s.done),
        steps_total=len(found.steps),
        rows=[row_read(r) for r in found.rows],
        days=days_of(found.rows),
        total=found.total,
    )
