"""What the view endpoints (/api/views) answer: one screen of the finode app each, shaped as that screen shows it."""

from datetime import date as Date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from .account import CardBill
from .day import Day
from .entry import ExpenseShare, IncomeShare, Share
from .shared_expense import ExpensePreview
from .shared_income import IncomePreview
from .transaction import RelatedRef

Kind = Literal["expense", "income", "transfer"]


class RowRead(BaseModel):
    """One row of a list of transactions (services/transaction_rows.TransactionRow)."""

    id: UUID
    date: Date
    title: str
    sub: str
    amount: Decimal
    kind: Kind
    # An opening balance or an adjustment against the system's Opening Balances account.
    is_system: bool
    # One account's opening balance: several on one day fold into one row.
    is_opening: bool
    related: RelatedRef | None
    recurring: bool
    by_assistant: str | None


class DayTotal(BaseModel):
    """What a day of the list spent, for a day with more than one entry."""

    date: Date
    spent: Decimal


class FilterSummary(BaseModel):
    """How many entries a filter found and, when they all go one way, what they come to ("spent" or "earned")."""

    count: int
    total: Decimal | None
    word: str


class UpcomingRead(BaseModel):
    """An entry dated ahead, as the "upcoming" card lists it."""

    id: UUID
    date: Date
    title: str
    sub: str
    amount: Decimal
    income: bool


class AppliedFilter(BaseModel):
    key: Literal["account", "category", "merchant", "tag"]
    label: str
    name: str


class TransactionsView(BaseModel):
    """A page of the Transactions list for one month."""

    month: str
    is_current: bool
    rows: list[RowRead]
    days: list[DayTotal]
    total: int
    summary: FilterSummary | None
    upcoming: list[UpcomingRead]
    upcoming_total: Decimal | None
    error: str | None
    applied: list[AppliedFilter]


class FilterChoice(BaseModel):
    id: UUID
    name: str
    sub: str


class FilterOptions(BaseModel):
    accounts: list[FilterChoice]
    categories: list[FilterChoice]
    merchants: list[str]


class LineRead(BaseModel):
    """One side's line in a transaction's details."""

    name: str
    amount: Decimal
    posted_on: Date | None


class PersonRef(BaseModel):
    id: UUID
    name: str


class TransactionDetails(BaseModel):
    """What the details sheet shows about one transaction."""

    row: RowRead
    from_label: str
    to_label: str
    from_lines: list[LineRead]
    to_lines: list[LineRead]
    comment: str | None
    tags: list[str]
    related_to: RowRead | None
    related: list[RowRead]
    # An entry made through a person (a loan, a shared bill, a settlement).
    person: PersonRef | None
    # A loan, a borrowing or a bill shared with people: edited here too. Otherwise the person's page looks after it.
    loan_like: bool
    with_names: list[str]
    source: str | None
    source_url: str | None
    external_id: str | None
    added_by: str | None
    changed_by: str | None


class GlanceRead(BaseModel):
    """Home's budget at a glance for the month."""

    has_budget: bool
    left: Decimal
    spent: Decimal
    assigned: Decimal
    carried: Decimal
    of: Decimal
    percent: int
    pace: int | None


class StepRead(BaseModel):
    """A first step for a new person; the app knows where each `key` leads."""

    key: Literal["account", "spend", "budget"]
    title: str
    done: bool
    hint: str | None


class HomeView(BaseModel):
    month: str
    is_current: bool
    has_recorded: bool
    glance: GlanceRead
    # The month's spending, for a person with no budget yet.
    spent: Decimal
    # The first steps while some are left; null once all are done.
    steps: list[StepRead] | None
    steps_done: int
    steps_total: int


class FormRow(BaseModel):
    """One row of the Add screen: what it shows (an account, a category or a person) and, when it has one, its amount,
    the category of a payment into a loan or fund, and the day it posts."""

    choice: UUID | None
    amount: Decimal | None
    category_id: UUID | None
    posted_on: Date | None


class PickOptionRead(BaseModel):
    id: UUID
    label: str
    budget: bool
    balance: Decimal | None


class PickGroupRead(BaseModel):
    """One group of the pickers, named for its type: Assets, Liabilities, Equity, People, Income or Expenses."""

    title: str
    options: list[PickOptionRead]


class ParentOption(BaseModel):
    """Where a new account can go (the Add screen's "New account" sheet): a root or a group, at its depth, and whether an
    account made there can start with a balance."""

    id: UUID
    name: str
    depth: int
    root: str
    opening_balance: bool


class CategoryParent(BaseModel):
    """A top-level category a new one can go under."""

    id: UUID
    name: str
    kind: Literal["spending", "earning"]


class EntryFormView(BaseModel):
    """Where the Add screen starts, and what its pickers offer."""

    editing: bool
    kind: Literal["expense", "income", "transfer", "other"]
    date: Date
    total: Decimal | None
    payee: str
    payee_person: PersonRef | None
    comment: str
    tags: list[str]
    related: RowRead | None
    from_rows: list[FormRow]
    to_rows: list[FormRow]
    # "split": a bill or an income shared with people, with the share below for its kind.
    mode: Literal["simple", "split"]
    # The people a bill or an income can be shared with (the active ones).
    people: list[PersonRef]
    expense_share: ExpenseShare
    income_share: IncomeShare
    # An entry another way of recording looks after (a settlement with a person): their page opens instead.
    person_page: UUID | None
    groups: list[PickGroupRead]
    account_parents: list[ParentOption]
    category_parents: list[CategoryParent]


class SharePreviewAsk(BaseModel):
    """What the Split would save, as typed so far."""

    total: Decimal
    date: Day | None = None
    payee: str = ""
    share: Share


class SharePreview(BaseModel):
    """What a bill or an income shared with people would do: `expense` for a bill, `income` for an income."""

    kind: Literal["expense", "income"]
    expense: ExpensePreview | None = None
    income: IncomePreview | None = None


class CardNoteRead(BaseModel):
    """The quiet line under a card's balance (services/accounts_view.CardNote): a bill ("overdue", or "due" on `on`,
    `soon` when it is near), no entries yet ("empty"), or none since `on` ("stale")."""

    kind: Literal["overdue", "due", "empty", "stale"]
    on: Date | None
    soon: bool


class AccountCard(BaseModel):
    """One account as a card on the Accounts page or a group's page."""

    id: UUID
    name: str
    balance: Decimal
    on_budget: bool
    closed: bool
    pinned: bool
    note: CardNoteRead | None


class KindRow(BaseModel):
    """One row of cards on the Accounts page: a kind of account and its accounts."""

    name: str
    group_id: UUID | None
    total: Decimal
    # A liability's total reads "owed".
    owed: bool
    open_count: int
    # Every account in it is closed (or the group itself is): the row shows only with the closed accounts.
    all_closed: bool
    add_url: str
    cards: list[AccountCard]


class AccountsView(BaseModel):
    net_worth: Decimal
    account_count: int
    has_budget_accounts: bool
    pinned: list[AccountCard]
    kinds: list[KindRow]
    # Some accounts are closed: "Load more" shows them.
    has_closed: bool


class RegisterRowRead(BaseModel):
    """One entry on an account's or a category's own page (services/transaction_rows.RegisterRow)."""

    id: UUID
    date: Date
    title: str
    sub: str
    posts_on: Date | None
    related: RelatedRef | None
    amount: Decimal
    # Money coming in: green, with "+".
    inflow: bool
    # A category's line that went the other way: "−".
    negative: bool
    # The account's running balance (none on a category's page).
    balance: Decimal | None


class AccountView(BaseModel):
    """An account's (or a group's) own page."""

    id: UUID
    name: str
    details: str | None
    badge: Literal["system", "closed"] | None
    sub: str
    closed_on: Date | None
    balance: Decimal
    # The balance the entries dated ahead leave.
    balance_after: Decimal | None
    # Part of a group's balance posted to the group itself.
    direct: Decimal | None
    bill: CardBill | None
    can_set_days: bool
    is_group: bool
    has_children: bool
    cards: list[AccountCard]
    can_add_child: bool
    can_pin: bool
    pinned: bool
    can_edit: bool
    postable: bool
    new_transaction_url: str | None
    upcoming: list[UpcomingRead]
    upcoming_total: Decimal | None
    entries: list[RegisterRowRead]
    has_more: bool
    next_offset: int


class CategoryRowRead(BaseModel):
    """One row of the Categories page: a top-level category, its month, what is inside it and its share."""

    id: UUID
    name: str
    total: Decimal
    # The biggest categories inside it ("Fuel · Taxi · +2").
    hint: str
    # Its part of the month ("34%", "<1%", "0%"; empty when the month adds up to nothing).
    share: str


class CategoriesView(BaseModel):
    month: str
    is_current: bool
    tab: Literal["expense", "income"]
    grand: Decimal
    rows: list[CategoryRowRead]


class CategoryRef(BaseModel):
    id: UUID
    name: str


class SubcategoryRead(BaseModel):
    id: UUID
    name: str
    total: Decimal


class CategoryView(BaseModel):
    """A category's own page for one month."""

    id: UUID
    name: str
    details: str | None
    kind: Literal["spending", "earning"]
    built_in: bool
    closed_on: Date | None
    group: CategoryRef | None
    month: str
    is_current: bool
    # The whole category's month, its subcategories too.
    total: Decimal
    subs: list[SubcategoryRead]
    # What was labelled with the category itself besides its subcategories ("Everything else").
    own_here: Decimal
    can_add_child: bool
    can_delete: bool
    entries: list[RegisterRowRead]


class KindChoiceRead(BaseModel):
    """A place a new account can go (a kind chip, or the place it was opened for), with what the form then asks."""

    id: UUID
    name: str
    root: str
    can_budget: bool
    can_bill: bool
    # Whether the "Part of the budget" box starts ticked for an account made there.
    budget_default: bool


class PlacedRead(BaseModel):
    """What the form says instead of the kind chips when it was opened for a place that is not a kind ("Kind · Other",
    "Inside · HDFC")."""

    label: str
    value: str


class AccountFormView(BaseModel):
    editing: bool
    is_group: bool
    name: str
    details: str | None
    balance: Decimal | None
    parent_id: UUID | None
    kinds: list[KindChoiceRead]
    placed: PlacedRead | None
    parent_options: list[KindChoiceRead]
    root_name: str | None
    can_budget: bool
    can_bill: bool
    on_budget: bool
    statement_day: int | None
    due_day: int | None
    bill_rounding: Literal["none", "nearest", "up"]
    # A group's own choice for the accounts made in it (null for an account).
    new_accounts_in_budget: bool | None


class CategoryFormView(BaseModel):
    editing: bool
    kind: Literal["spending", "earning"]
    name: str
    details: str | None
    parent_id: UUID | None
    groups: list[CategoryRef]
