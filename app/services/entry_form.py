"""Where the Add screen starts: the rows, the kind and the amount of a new entry (blank, from an account or a category, a
repeat, a related entry, a card bill to pay, money to or from a person) or of one being edited. The web form and the
finode app's form view (/api/views/entry-form) both start from here."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from uuid import UUID

from ..models.contact import Contact
from ..models.transaction import PostingSide
from ..schemas.shared_expense import SharedExpenseRead
from ..schemas.shared_income import SharedIncomeRead
from ..schemas.transaction import PostingBase, PostingCreate, TransactionRead
from .account import AccountService
from .account_tree import build_tree
from .category import CategoryService
from .contact import ContactService
from .entry import infer_kind, root_of
from .expense_sharing import ExpenseSharingService
from .income_sharing import IncomeSharingService
from .transaction import TransactionService
from .transaction_rows import AccountIndex, TransactionRow, related_info
from .transfer import TransferService


def form_rows(
    postings: Iterable[PostingBase | PostingCreate],
    side: PostingSide,
    account_id: UUID | None = None,
    roots: dict[UUID, str] | None = None,
    person_of: Mapping[UUID, UUID] | None = None,
) -> list[dict]:
    """The rows of one side of the form: the transaction's own postings, or one blank row (maybe with an account).
    A line on Expenses or Income is picked by its category, which is what the row shows."""
    found = [
        {
            "posting": p,
            "account": p.category_id
            if roots and p.category_id and root_of(roots, p.account_id) in ("Expenses", "Income")
            else (person_of or {}).get(p.account_id, p.account_id)  # a person's account shows as the person
            if p.account_id is not None
            else None,
        }
        for p in postings
        if p.side == side
    ]
    return found or [{"posting": None, "account": account_id}]


@dataclass
class EntryStart:
    """Where the form starts. `rows` are form_rows' dicts (`posting`, `account`: the account, category or person the row
    shows)."""

    kind: str
    total: Decimal | str
    from_rows: list[dict]
    to_rows: list[dict]
    payee: str = ""
    comment: str = ""
    tags: list[str] = field(default_factory=list)
    related: TransactionRow | None = None
    copy_of: TransactionRead | None = None


def _amount(text: str) -> str:
    try:
        return str(Decimal(text.replace(",", "").strip())) if text.strip() else ""
    except InvalidOperation:
        return ""


def new_start(
    accounts: AccountService,
    categories: CategoryService,
    transactions: TransactionService,
    contacts: ContactService,
    account: UUID | None = None,
    category: UUID | None = None,
    repeat: UUID | None = None,
    related: UUID | None = None,
    pay: UUID | None = None,
    amount: str = "",
    move: str = "",
    with_person: UUID | None = None,
) -> EntryStart:
    """A new entry: blank, or opened from an account or a category, as a repeat of an entry (dated today), related to
    one, to pay a card or loan, or to lend, borrow or settle with a person. LookupError for what is not the person's."""
    all_accounts = accounts.list()
    roots = {n.account.id: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
    if repeat is not None:
        again = transactions.read(repeat)
        if again is None:
            raise LookupError("transaction not found")
        return EntryStart(
            kind=infer_kind(again.postings, roots),
            total=sum((p.amount for p in again.postings if p.side == PostingSide.DEBIT), Decimal(0)),
            from_rows=form_rows(again.postings, PostingSide.CREDIT, roots=roots),
            to_rows=form_rows(again.postings, PostingSide.DEBIT, roots=roots),
            payee=again.payee or "",
            comment=again.comment or "",
            tags=list(again.tags or []),
            copy_of=again,
        )
    linked = None
    if related is not None:
        linked = related_info(
            transactions, AccountIndex.build(all_accounts, categories.list(include_closed=True)), related
        )
        if linked is None:
            raise LookupError("transaction not found")
    from_id = to_id = None
    kind = {"Income": "income", "Equity": "other"}.get(roots.get(account, "") if account else "", "expense")
    if account is not None and account in roots:
        from_id = account  # the money leaves the account the entry is started from
    total = ""
    if pay is not None and roots.get(pay) == "Liabilities":
        to_id, kind, total = pay, "transfer", _amount(amount)
    if move in ("lend", "borrow", "settle") and with_person is not None:
        person = contacts.read(with_person)
        if person is None:
            raise LookupError("person not found")
        kind = "transfer"
        # Settle: they pay you what they owe, or you pay what you owe them.
        pays_you = move == "borrow" or (move == "settle" and person.receivable > 0)
        from_id, to_id = (person.id, None) if pays_you else (None, person.id)
        if move == "settle":
            total = str(person.receivable if pays_you else person.payable)
    chosen = categories.read(category) if category is not None else None
    if chosen is not None:
        if chosen.kind == "spending":
            to_id = chosen.id
        else:
            from_id, kind = chosen.id, "income"
    return EntryStart(
        kind=kind,
        total=total,
        from_rows=form_rows([], PostingSide.CREDIT, from_id),
        to_rows=form_rows([], PostingSide.DEBIT, to_id),
        related=linked,
    )


@dataclass
class EditStart(EntryStart):
    """An entry being edited, with what the people services made of it."""

    transaction: TransactionRead | None = None
    mode: str = "simple"  # "split": a bill or income shared with people
    bill: SharedExpenseRead | None = None
    shared_income: SharedIncomeRead | None = None
    payee_person: Contact | None = None
    # An entry another way of recording looks after (a settlement, an opening balance with a person): their page.
    person_page: UUID | None = None
    keep_people: set[UUID] = field(default_factory=set)


def edit_start(
    transaction_id: UUID,
    accounts: AccountService,
    categories: CategoryService,
    transactions: TransactionService,
    contacts: ContactService,
    transfers: TransferService,
    expenses: ExpenseSharingService,
    incomes: IncomeSharingService,
) -> EditStart:
    """An entry being edited. A loan or borrowing is edited here (the person shows on its side) and so is a bill or income
    shared with people (its shares, as entered); anything else a person made says whose page looks after it. A gift is an
    ordinary entry that names the person as its payee. LookupError for an entry that is not the person's."""
    transaction = transactions.read(transaction_id)
    if transaction is None:
        raise LookupError("transaction not found")
    person_of: dict[UUID, UUID] = {}
    party = contacts.made_of(transaction_id)
    purposes = {r.purpose for r in party}
    bill = shared_income = None
    if party:
        if purposes == {"expense"}:
            bill = expenses.of_entry(transaction_id)
        if purposes == {"income"}:
            shared_income = incomes.read(transaction_id)
        if bill is None and shared_income is None and not purposes <= {"loan", "borrowing"}:
            return EditStart(
                kind="other",
                total="",
                from_rows=[],
                to_rows=[],
                transaction=transaction,
                person_page=party[0].contact_id,
            )
        person_of = contacts.person_by_account()
    roots = {n.account.id: r.account.name for r in build_tree(accounts.list()) for n in r.walk()}
    start = EditStart(
        kind=infer_kind(transaction.postings, roots),
        total=sum((p.amount for p in transaction.postings if p.side == PostingSide.DEBIT), Decimal(0)),
        from_rows=form_rows(transaction.postings, PostingSide.CREDIT, roots=roots, person_of=person_of),
        to_rows=form_rows(transaction.postings, PostingSide.DEBIT, roots=roots, person_of=person_of),
        payee=transaction.payee or "",
        comment=transaction.comment or "",
        tags=list(transaction.tags or []),
        related=related_info(
            transactions,
            AccountIndex.build(accounts.list(), categories.list(include_closed=True)),
            transaction.related_id,
        ),
        transaction=transaction,
        keep_people={r.contact_id for r in party},
    )
    if bill is not None:
        start.total, start.mode, start.kind, start.bill = bill.total_amount, "split", "expense", bill
    elif shared_income is not None:
        start.total, start.mode, start.kind, start.shared_income = (
            shared_income.total_amount,
            "split",
            "income",
            shared_income,
        )
    if start.mode == "split":
        start.from_rows, start.to_rows = form_rows([], PostingSide.CREDIT), form_rows([], PostingSide.DEBIT)
    named = transfers.gift_of(transaction_id)
    start.payee_person = contacts.get(named) if named else None
    return start
