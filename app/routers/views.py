"""JSON API for the finode app's screens (`/api/views`): one call answers what one screen shows, built from the same
rows as the web pages (services/transaction_rows.py), so the app works out nothing the server already knows."""

import calendar
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from ..auth import require_authenticated_user
from ..clock import local_today
from ..dependencies import (
    Accounts,
    Budget,
    Categories,
    Contacts,
    Recurring,
    Reports,
    SharedExpenses,
    SharedIncomes,
    Transactions,
    Transfers,
)
from ..repositories.transaction import SYSTEM_PAYEES
from ..schemas.entry import EntryForm, ExpenseShare
from ..schemas.views import (
    AccountCard,
    AccountFormView,
    AccountsView,
    AccountView,
    AppliedFilter,
    CardNoteRead,
    CategoriesView,
    CategoryFormView,
    CategoryParent,
    CategoryRef,
    CategoryRowRead,
    CategoryView,
    DayTotal,
    EntryFormView,
    FilterChoice,
    FilterOptions,
    FilterSummary,
    FormRow,
    GlanceRead,
    HomeView,
    KindChoiceRead,
    KindRow,
    LineRead,
    ParentOption,
    PersonRef,
    PickGroupRead,
    PickOptionRead,
    PlacedRead,
    RegisterRowRead,
    RowRead,
    SharePreview,
    SharePreviewAsk,
    StepRead,
    SubcategoryRead,
    TransactionDetails,
    TransactionsView,
    UpcomingRead,
)
from ..services import cards
from ..services.account_tree import Node, build_tree, without_contacts
from ..services.accounts_view import (
    AccountForm,
    CardNote,
    KindChoice,
    account_page,
    accounts_page,
    edit_account_form,
    new_account_form,
)
from ..services.categories_view import TABS, categories_page, category_form, category_page
from ..services.entry_form import EditStart, EntryStart, edit_start, new_start
from ..services.entry_share import expense_create, expense_start, income_create, income_start
from ..services.home import home_view
from ..services.pickers import (
    ACCOUNT_ROOTS,
    OPENING_BALANCE_ROOTS,
    category_groups,
    parent_options,
    people_group,
    posting_groups,
)
from ..services.transaction_rows import (
    PAGE_SIZE,
    AccountIndex,
    ListFilters,
    RegisterRow,
    TransactionRow,
    day_totals,
    filter_options,
    month_list,
    to_row,
    transaction_details,
)
from ..services.validation import validation_message
from .contact_utils import refused

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
    """Home for a month (`YYYY-MM`, never ahead): the budget at a glance and a new person's first steps while some are
    left. The month's entries are the list's (`/views/transactions`), so every page of them refreshes together."""
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
    )


def _form_rows(rows: list[dict]) -> list[FormRow]:
    out = []
    for r in rows:
        posting, choice = r["posting"], r["account"]
        out.append(
            FormRow(
                choice=choice,
                amount=posting.amount if posting is not None else None,
                # A row on an account can carry the category of a payment into a loan or fund; a category row is it.
                category_id=posting.category_id if posting is not None and posting.category_id != choice else None,
                posted_on=getattr(posting, "posted_on", None) if posting is not None else None,
            )
        )
    return out


@router.get("/entry-form", response_model=EntryFormView)
def entry_form(
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    contacts: Contacts,
    transfers: Transfers,
    expenses: SharedExpenses,
    incomes: SharedIncomes,
    transaction_id: UUID | None = None,
    account: UUID | None = None,
    category: UUID | None = None,
    repeat: UUID | None = None,
    related: UUID | None = None,
    pay: UUID | None = None,
    amount: str = "",
    move: str = "",
    with_person: UUID | None = Query(default=None, alias="with"),
    mode: str = "",
):
    """Where the Add screen starts (`transaction_id` to edit; otherwise blank, or opened from an `account` or a
    `category`, as a `repeat`, `related` to an entry, to `pay` a card with `amount`, to `move` money `with` a person, or
    with `mode=split` to share a bill `with` a person), and what its pickers offer: the accounts by type with their
    balances and budget flags, the people, the categories, and where a new account or category can go."""
    try:
        if transaction_id is not None:
            start: EntryStart = edit_start(
                transaction_id, accounts, categories, transactions, contacts, transfers, expenses, incomes
            )
        else:
            start = new_start(
                accounts,
                categories,
                transactions,
                contacts,
                account,
                category,
                repeat,
                related,
                pay,
                amount,
                move,
                with_person,
            )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    edit = start if isinstance(start, EditStart) else None
    split = edit.mode == "split" if edit else mode == "split" and repeat is None
    tree = build_tree(accounts.list())
    people = [c for c in contacts.people() if c.archived_at is None] if contacts.has_people() else []
    transaction = edit.transaction if edit else None
    used = transaction.postings if transaction is not None else ()
    payee_person = edit.payee_person if edit else None
    return EntryFormView(
        editing=edit is not None,
        kind="expense"
        if split and edit is None
        else start.kind
        if start.kind in ("expense", "income", "transfer")
        else "other",
        date=transaction.date if transaction is not None else local_today(),
        total=start.total if start.total != "" else None,
        payee=start.payee,
        payee_person=PersonRef(id=payee_person.id, name=payee_person.name) if payee_person else None,
        comment=start.comment,
        tags=start.tags,
        related=row_read(start.related) if start.related else None,
        from_rows=_form_rows(start.from_rows),
        to_rows=_form_rows(start.to_rows),
        mode="split" if split else "simple",
        people=[PersonRef(id=c.id, name=c.name) for c in people],
        expense_share=expense_start(
            edit.bill if edit else None, with_person if split and edit is None and not move else None
        ),
        income_share=income_start(edit.shared_income if edit else None),
        person_page=edit.person_page if edit else None,
        groups=[
            PickGroupRead(
                title=title,
                options=[PickOptionRead(id=o.id, label=o.label, budget=o.budget, balance=o.balance) for o in options],
            )
            for title, options in (
                *posting_groups(tree, {p.account_id for p in used}),
                *people_group(contacts, edit.keep_people if edit else set()),
                *category_groups(categories.list(include_closed=True), {p.category_id for p in used if p.category_id}),
            )
        ],
        account_parents=[
            ParentOption(
                id=n.account.id,
                name=n.account.name,
                depth=n.depth,
                root=root.account.name,
                opening_balance=root.account.name in OPENING_BALANCE_ROOTS,
            )
            for root in without_contacts(tree)
            if root.account.name in ACCOUNT_ROOTS
            for n in parent_options([root])
        ],
        category_parents=[
            CategoryParent(id=c.id, name=c.name, kind=c.kind) for c in categories.list() if c.parent_id is None
        ],
    )


@router.post("/entry-share-preview", response_model=SharePreview)
def entry_share_preview(ask: SharePreviewAsk, contacts: Contacts, expenses: SharedExpenses, incomes: SharedIncomes):
    """What the Add screen's Split would do, as typed so far: each share and what is owed for a bill, your income and
    the people's parts for an income. Nothing is saved. A Split that cannot be saved yet is refused with the reason (400;
    404 for a person, account or category that is not the caller's), which the screen shows in place of the preview."""
    form = EntryForm(kind=ask.share.kind, payee=ask.payee, date=ask.date, total=ask.total, share=ask.share)
    people = {c.id for c in contacts.people()} if contacts.has_people() else set()
    try:
        if isinstance(ask.share, ExpenseShare):
            return SharePreview(kind="expense", expense=expenses.preview(expense_create(form, ask.share, people)))
        return SharePreview(kind="income", income=incomes.preview(income_create(form, ask.share, people)))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=validation_message(e)) from None
    except ValueError as e:
        raise refused(e) from None


RELATED_LIMIT = 30


@router.get("/related-entries", response_model=list[RowRead])
def related_entries(
    accounts: Accounts, categories: Categories, transactions: Transactions, q: str = "", exclude: UUID | None = None
):
    """Earlier entries a new one can be related to: the newest 30 up to today, narrowed by `q` (payee, note or account),
    without `exclude` (the entry being edited) and the system's opening balances."""
    index = _index(accounts, categories)
    found = transactions.list(text=q, limit=RELATED_LIMIT + 1, date_to=local_today())
    return [row_read(to_row(t, index)) for t in found if t.id != exclude and t.payee not in SYSTEM_PAYEES][
        :RELATED_LIMIT
    ]


# ---- Accounts ---------------------------------------------------------------------------------------------------------


def _note(note: CardNote | None) -> CardNoteRead | None:
    return CardNoteRead(kind=note.kind, on=note.on, soon=note.soon) if note else None


def _card(node: Node, notes: dict[UUID, CardNote]) -> AccountCard:
    account = node.account
    return AccountCard(
        id=account.id,
        name=account.name,
        balance=account.balance,
        on_budget=account.on_budget,
        closed=account.closed_on is not None,
        pinned=account.pinned,
        note=_note(notes.get(account.id)),
    )


def register_read(row: RegisterRow) -> RegisterRowRead:
    return RegisterRowRead(**vars(row))


@router.get("/accounts", response_model=AccountsView)
def accounts_view(accounts: Accounts):
    """The Accounts page: net worth, the pinned accounts, and a row of cards per kind (Bank Accounts, Credit Cards…, then
    the groups the person made, then the plain accounts), each card with its balance and its one quiet line (a bill, no
    entries yet, none for a month). Closed accounts are listed too, marked, for "Load more"."""
    page = accounts_page(accounts, local_today())
    return AccountsView(
        net_worth=page.net_worth,
        account_count=page.account_count,
        has_budget_accounts=page.has_budget_accounts,
        pinned=[_card(n, page.notes) for n in page.pinned],
        kinds=[
            KindRow(
                name=k.name,
                group_id=k.group_id,
                total=k.total,
                owed=k.owed,
                open_count=k.open_count,
                all_closed=k.all_closed,
                add_url=k.add_url,
                cards=[_card(n, page.notes) for n in k.items],
            )
            for k in page.kinds
        ],
        has_closed=page.has_closed,
    )


@router.get("/accounts/{account_id}", response_model=AccountView)
def account_view(account_id: UUID, accounts: Accounts, offset: int = Query(default=0, ge=0)):
    """An account's (or a group's) own page: its balance, a card's bill, a group's open accounts as cards, what is dated
    ahead, and its entries newest first with the running balance, a chunk at a time (`offset`: the `next_offset` of the
    chunk before)."""
    try:
        page = account_page(accounts, account_id, local_today(), offset)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    node, account = page.node, page.node.account
    return AccountView(
        id=account.id,
        name=account.name,
        details=account.details,
        badge="system" if node.kind == "system" else "closed" if account.closed_on else None,
        sub=page.sub,
        closed_on=account.closed_on,
        balance=account.balance,
        balance_after=page.balance_after,
        direct=page.direct,
        bill=page.bill,
        bill_soon=page.bill is not None and page.bill.bill > 0 and 0 <= page.bill.days_to_due <= cards.DUE_SOON_DAYS,
        can_set_days=page.can_set_days,
        is_group=node.is_group,
        has_children=bool(node.children),
        cards=[_card(n, page.notes) for n in page.cards],
        can_add_child=page.can_add_child,
        can_pin=page.can_pin,
        pinned=account.pinned,
        can_edit=node.kind == "user",
        postable=node.postable,
        new_transaction_url=page.new_transaction_url,
        upcoming=[
            UpcomingRead(id=u.transaction_id, date=u.date, title=u.title, sub=u.sub, amount=u.amount, income=u.income)
            for u in page.upcoming
        ],
        upcoming_total=page.upcoming_total,
        entries=[register_read(r) for r in page.entries],
        has_more=page.has_more,
        next_offset=page.next_offset,
    )


# ---- Categories -------------------------------------------------------------------------------------------------------


def _month_span(month: str) -> tuple[date, date, bool]:
    """The month asked for (this month for anything else, never one that has not started) and the days it counts: up to
    today for this month."""
    today = local_today()
    when = parse_month(month, today)
    last = when.replace(day=calendar.monthrange(when.year, when.month)[1])
    return when, min(last, today), when == today.replace(day=1)


@router.get("/categories", response_model=CategoriesView)
def categories_view(categories: Categories, reports: Reports, month: str = "", tab: str = "expense"):
    """The Categories page for a month (`YYYY-MM`; this month by default) and a tab (`expense` or `income`): what each
    top-level category came to, biggest first, with the biggest inside it (`hint`) and its share of the month."""
    when, end, is_current = _month_span(month)
    shown = tab if tab in TABS else "expense"
    rows, grand = categories_page(categories, reports, TABS[shown], when, end)
    return CategoriesView(
        month=when.strftime("%Y-%m"),
        is_current=is_current,
        tab="income" if shown == "income" else "expense",
        grand=grand,
        rows=[
            CategoryRowRead(id=r.node.category.id, name=r.node.category.name, total=r.total, hint=r.hint, share=r.share)
            for r in rows
        ],
    )


@router.get("/categories/{category_id}", response_model=CategoryView)
def category_view(category_id: UUID, categories: Categories, reports: Reports, month: str = ""):
    """A category's own page for a month: the whole category's figure, its subcategories with theirs and what was
    labelled with it itself besides them (`own_here`), and its own entries newest first."""
    when, end, is_current = _month_span(month)
    try:
        page = category_page(categories, reports, category_id, when, end)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    category = page.category
    return CategoryView(
        id=category.id,
        name=category.name,
        details=category.details,
        kind=category.kind,
        built_in=category.system_key is not None,
        closed_on=category.closed_on,
        group=CategoryRef(id=page.group.id, name=page.group.name) if page.group else None,
        month=when.strftime("%Y-%m"),
        is_current=is_current,
        total=page.total,
        subs=[SubcategoryRead(id=n.category.id, name=n.category.name, total=t) for n, t in page.subs],
        own_here=page.own_here,
        can_add_child=page.can_add_child,
        can_delete=category.system_key is None and category.closed_on is None,
        entries=[register_read(r) for r in page.entries],
    )


# ---- the forms ----------------------------------------------------------------------------------------------------


def _kind(choice: KindChoice) -> KindChoiceRead:
    account = choice.node.account
    return KindChoiceRead(
        id=account.id,
        name=account.name,
        root=choice.root,
        can_budget=choice.can_budget,
        can_bill=choice.can_bill,
        budget_default=choice.budget_default,
    )


@router.get("/account-form", response_model=AccountFormView)
def account_form_view(accounts: Accounts, account_id: UUID | None = None, parent: UUID | None = None, root: str = ""):
    """Where the account form starts: editing `account_id`, or a new account (opened for a kind with `parent`, or for the
    plain accounts of a type with `root` = `assets` or `liabilities`). The `kinds` (and `parent_options`) say for each
    place whether an account there can be part of the budget, takes a card's days, and starts in the budget."""
    try:
        form: AccountForm = (
            edit_account_form(accounts, account_id)
            if account_id is not None
            else new_account_form(accounts, parent, root)
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    account = form.node.account if form.node else None
    return AccountFormView(
        editing=account is not None,
        is_group=form.node.is_group if form.node else False,
        name=account.name if account else "",
        details=account.details if account else None,
        balance=account.balance if account else None,
        parent_id=form.parent_id,
        kinds=[_kind(k) for k in form.kinds],
        placed=PlacedRead(label=form.placed[0], value=form.placed[1]) if form.placed else None,
        parent_options=[_kind(k) for k in form.parent_options],
        root_name=form.root_name,
        can_budget=form.can_budget,
        can_bill=form.can_bill,
        on_budget=bool(form.on_budget),
        statement_day=account.statement_day if account else None,
        due_day=account.due_day if account else None,
        bill_rounding=account.bill_rounding if account else "none",
        new_accounts_in_budget=account.new_accounts_in_budget if account else None,
    )


@router.get("/category-form", response_model=CategoryFormView)
def category_form_view(
    categories: Categories, category_id: UUID | None = None, parent: UUID | None = None, root: str = "expense"
):
    """Where the category form starts: editing `category_id`, or a new category (`root` = `expense` or `income`; inside
    the group `parent`, whose kind it takes). `groups` are where it can go (none for a group that holds categories)."""
    try:
        form = category_form(categories, category_id, parent, root)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    current = form.category
    return CategoryFormView(
        editing=current is not None,
        kind="earning" if form.kind == "earning" else "spending",
        name=current.name if current else "",
        details=current.details if current else None,
        parent_id=form.parent_id,
        groups=[CategoryRef(id=g.id, name=g.name) for g in form.groups],
    )
