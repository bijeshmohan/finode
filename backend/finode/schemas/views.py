"""What the view endpoints (/api/views) answer: one screen of the finode app each, shaped as that screen shows it."""

from datetime import date as Date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from .account import AccountType, CardBill
from .day import Day
from .entry import ExpenseShare, IncomeShare, Share
from .shared_expense import ExpensePreview
from .shared_income import IncomePreview
from .todo import TodoRule
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
    # The icon the row leads with (services/row_icon.py; finode/category_icons.py).
    icon: str


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
    # The icon the row leads with (services/row_icon.py; finode/category_icons.py).
    icon: str


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
    # A category's icon; none for an account.
    icon: str | None = None


class PickGroupRead(BaseModel):
    """One group of the pickers, named for its type: Assets, Liabilities, Equity, People, Income or Expenses."""

    title: str
    options: list[PickOptionRead]


class AccountTypeOption(BaseModel):
    """What a new account made from the Add screen's "New account" sheet can be: one of the four types."""

    key: AccountType
    name: str
    icon: str
    # Assets or Liabilities: the sheet offers the types of the side it was opened for.
    root: str


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
    account_types: list[AccountTypeOption]


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
    closed: bool
    pinned: bool
    note: CardNoteRead | None
    # Its type's icon (services/account_types.TYPE_ICONS); null for an account with no type.
    icon: str | None


class KindRow(BaseModel):
    """One row of cards on the Accounts page: one of the four types and its accounts."""

    name: str
    type: AccountType
    icon: str
    total: Decimal
    # A liability's total reads "owed".
    owed: bool
    # Every account in it is closed: the row shows only with the closed accounts.
    all_closed: bool
    add_url: str
    cards: list[AccountCard]


class AccountsView(BaseModel):
    account_count: int
    # The hero card: what the Bank, Cash and Prepaid Wallet accounts hold, and what is owed on the cards, apart.
    in_accounts: Decimal
    owed_on_cards: Decimal
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
    # The icon the row leads with; none on a category's page (its header shows it once).
    icon: str | None = None


class AccountView(BaseModel):
    """An account's (or a group's) own page."""

    id: UUID
    name: str
    # Its type's icon; null for Opening Balances and the like.
    icon: str | None
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
    # Something left to pay, due within cards.DUE_SOON_DAYS (not yet overdue): the due line turns amber.
    bill_soon: bool
    can_set_days: bool
    is_group: bool
    has_children: bool
    cards: list[AccountCard]
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
    """One row of the Categories page: a category, its month and its share."""

    id: UUID
    name: str
    total: Decimal
    # Its part of the month ("34%", "<1%", "0%"; empty when the month adds up to nothing).
    share: str
    icon: str


class CategoriesView(BaseModel):
    month: str
    is_current: bool
    tab: Literal["expense", "income"]
    grand: Decimal
    rows: list[CategoryRowRead]


class CategoryRef(BaseModel):
    id: UUID
    name: str


class CategoryView(BaseModel):
    """A category's own page for one month."""

    id: UUID
    name: str
    icon: str
    details: str | None
    kind: Literal["spending", "earning"]
    built_in: bool
    closed_on: Date | None
    month: str
    is_current: bool
    # The category's month.
    total: Decimal
    can_delete: bool
    # Where the bar's "+" starts an entry on this page (for this category, coming back here); none once it is closed.
    new_transaction_url: str | None
    entries: list[RegisterRowRead]


class AccountTypeChoice(BaseModel):
    """One of the four types a new account can be (the form's switcher)."""

    key: AccountType
    name: str
    icon: str


class AccountFormView(BaseModel):
    editing: bool
    name: str
    details: str | None
    balance: Decimal | None
    # The account's type, or the one a new account was opened for; null until the person picks one.
    type: AccountType | None
    # The four types in the person's order (empty when editing: an account keeps its type).
    types: list[AccountTypeChoice]
    statement_day: int | None
    due_day: int | None
    bill_rounding: Literal["none", "nearest", "up"]


class CategoryFormView(BaseModel):
    editing: bool
    kind: Literal["spending", "earning"]
    name: str
    details: str | None
    # Its icon; none for a new category until one is chosen.
    icon: str | None = None
    # The built-in Uncategorised keeps its icon: the form offers no choice.
    icon_fixed: bool = False


class BudgetRowRead(BaseModel):
    """One row of the Budgets page (services/budget_view): a category with what is left, how its second line reads and
    how far its bar runs."""

    category_id: UUID
    name: str
    assigned: Decimal
    activity: Decimal
    available: Decimal
    overspent_last_month: Decimal
    # "of 25,000.00"; none when nothing is assigned, spent or left ("nothing assigned").
    of: Decimal | None
    state: Literal["overspent", "all_spent"] | None
    # What needs a look ("500.00 overspent last month"), or nothing.
    hint: str
    # How far the bar runs (100 when over).
    percent: int
    over: bool
    icon: str


class BudgetSum(BaseModel):
    """What Ready to assign is made of (the "i")."""

    money_in_accounts: Decimal
    reserved_for_cards: Decimal
    available: Decimal
    assigned_to_later_months: Decimal


class BudgetView(BaseModel):
    month: str
    is_current: bool
    # How far through the month today is (the current month only).
    pace: int | None
    ready_to_assign: Decimal
    sum: BudgetSum
    # What copying last month's amounts would assign (zero: nothing to copy).
    copyable: Decimal
    # A short welcome until the first amount is assigned.
    show_intro: bool
    has_budget_accounts: bool
    # More spent than there was to spend in all the categories together.
    overspent: Decimal
    rows: list[BudgetRowRead]


class MoveLine(BaseModel):
    category_id: UUID
    name: str
    available: Decimal


class BudgetMoveView(BaseModel):
    month: str
    source: UUID | None
    lines: list[MoveLine]


# ---- the to-do bell, Coming up, Recurring --------------------------------------------------------------------------


class TodoBill(BaseModel):
    account_id: UUID
    # The card's own name: "Visa" for Liabilities:Credit Card:Visa.
    name: str
    bill: Decimal
    due_date: Date
    # Negative once overdue.
    days_to_due: int


class CategoryChoice(BaseModel):
    id: UUID
    # "Food › Dining"
    path: str


class TodoView(BaseModel):
    count: int
    card_bills: list[TodoBill]
    failing_rules: list[TodoRule]


class ComingRowRead(BaseModel):
    title: str
    sub: str
    amount: Decimal
    income: bool
    # A rule's occurrence (not recorded yet) or an entry dated ahead: one of the two.
    recurring_id: UUID | None
    transaction_id: UUID | None
    # The icon the row leads with (services/row_icon.py; finode/category_icons.py).
    icon: str


class ComingDayRead(BaseModel):
    date: Date
    # Only when every row goes one way and there is more than one.
    total: Decimal | None
    rows: list[ComingRowRead]


class ComingUpView(BaseModel):
    through: Date
    count: int
    total: Decimal | None
    days: list[ComingDayRead]


class RuleRowRead(BaseModel):
    id: UUID
    # The payee, else the name of where the money goes.
    title: str
    amount: Decimal
    # "Every month", "Every 2 weeks"
    schedule: str
    status: Literal["active", "paused", "ended", "error"]
    next_date: Date
    last_error: str | None


class RecurringView(BaseModel):
    # Active rules and those that could not be recorded.
    live: list[RuleRowRead]
    # Paused and ended ones.
    stopped: list[RuleRowRead]


class FrequencyChoice(BaseModel):
    # "monthly"
    value: str
    # "month": one of them ("Every month", "Every 2 months")
    name: str


class RecurringFormView(BaseModel):
    """Where the recurring form starts: the rule's rows as the Add screen shows them (no posting day, no people), its
    schedule, and for a rule being edited where it stands."""

    editing: bool
    kind: Literal["expense", "income", "transfer", "other"]
    total: Decimal | None
    payee: str
    comment: str
    tags: list[str]
    from_rows: list[FormRow]
    to_rows: list[FormRow]
    groups: list[PickGroupRead]
    account_types: list[AccountTypeOption]
    frequency: str
    every: int
    start_date: Date
    end_date: Date | None
    frequencies: list[FrequencyChoice]
    # A rule being edited:
    status: Literal["active", "paused", "ended", "error"] | None = None
    schedule: str | None = None
    active: bool | None = None
    next_date: Date | None = None
    last_date: Date | None = None
    skipped_date: Date | None = None
    last_error: str | None = None


# ---- People ---------------------------------------------------------------------------------------------------------


class ShowChoice(BaseModel):
    key: str
    name: str


class PersonRowRead(BaseModel):
    id: UUID
    name: str
    # "Nothing yet", "Settled up", "Even · ₹50.00 each way", "Last 2 Nov", "Archived"
    sub: str
    # Above zero they owe you.
    net: Decimal


class PeopleView(BaseModel):
    show: Literal["all", "owed", "owe", "archived"]
    shows: list[ShowChoice]
    has_archived: bool
    # Whether there is anyone not archived.
    everyone: bool
    owed_total: Decimal
    owe_total: Decimal
    # The two apart, unsigned: the head's figure.
    difference: Decimal
    # What the head says: "Owed to you", "You owe" or "Everything is settled".
    label: str
    rows: list[PersonRowRead]


class OpenRowRead(BaseModel):
    transaction_id: UUID
    # "Loan", "Dinner", "Opening balance"
    name: str
    date: Date
    # "they owe you" / "you owe them": only when the person is owed both ways.
    who: str | None
    # What was paid back and of what, when part of it was.
    settled: Decimal | None
    original: Decimal
    outstanding: Decimal
    receivable: bool


class ActivityRowRead(BaseModel):
    transaction_id: UUID
    # "Loan", "Paid back", "Dinner", "Evened out"
    title: str
    date: Date
    # What follows the day: "their share", "their part", "received for you", or the entry's note.
    sub: str | None
    amount: Decimal
    # Money that came to you (a settlement or a gift from them): green.
    income: bool


class PersonView(BaseModel):
    id: UUID
    name: str
    phone: str | None
    email: str | None
    notes: str | None
    archived: bool
    receivable: Decimal
    payable: Decimal
    net: Decimal
    open: list[OpenRowRead]
    activity: list[ActivityRowRead]
    # How many older entries are not listed.
    more_activity: int


class PersonEntryView(BaseModel):
    transaction_id: UUID
    title: str
    date: Date
    amount: Decimal
    # The lines under the title, in order.
    notes: list[str]
    # An opening balance can be edited; everything but an evened-out entry can be reversed.
    can_edit: bool
    can_reverse: bool


class OpeningFormView(BaseModel):
    person_name: str
    editing: bool
    direction: Literal["receivable", "payable"]
    amount: Decimal | None
    date: Date
    description: str
    # What was already paid back (editing only): the amount can't go below it and the direction can't change.
    paid: Decimal | None
