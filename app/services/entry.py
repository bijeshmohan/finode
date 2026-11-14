"""Saving an entry from the Add screen, whatever it turns out to be: an ordinary entry (its rows' categories posting on
Expenses or Income), money to or from a person (a loan, a borrowing, paying back what is owed), or an expense or income
that names a person as a gift. Editing first releases what the entry was (a loan, a shared bill, shared income), and
rolls all of it back when the new version is refused. The web form and /api/entries both save through here.

Bills and income shared with people are saved by their own services (expense_sharing, income_sharing)."""

from collections.abc import Iterable, Mapping
from uuid import UUID

from pydantic import ValidationError

from ..clock import local_today
from ..models.transaction import PostingSide
from ..schemas.contact import TransferCreate
from ..schemas.entry import EntryForm, EntryRow, EntrySaved
from ..schemas.transaction import PostingBase, PostingCreate, TransactionCreate, TransactionUpdate
from .account import AccountService
from .account_tree import build_tree
from .category import CategoryService
from .contact import ContactService
from .expense_sharing import ExpenseSharingService
from .income_sharing import IncomeSharingService
from .transaction import TransactionService
from .transfer import TransferService
from .validation import validation_message

ASSET_LIKE = ("Assets", "Liabilities")


def root_of(roots: Mapping[UUID, str], account_id: UUID | None) -> str | None:
    """The top-level account (Assets, Expenses…) of a line's account; none for a line that names only a category."""
    return roots.get(account_id) if account_id is not None else None


def infer_kind(postings: Iterable[PostingBase | PostingCreate], roots: Mapping[UUID, str]) -> str:
    """What a set of postings is, for the form's Expense / Income / Transfer buttons: an expense is money from
    assets or liabilities into expenses, income comes from income into them, a transfer is between them;
    anything else (equity, refunds, mixed) is "other", which offers every account."""
    credit = {root_of(roots, p.account_id) for p in postings if p.side == PostingSide.CREDIT}
    debit = {root_of(roots, p.account_id) for p in postings if p.side == PostingSide.DEBIT}
    if debit == {"Expenses"} and credit and credit <= set(ASSET_LIKE):
        return "expense"
    if credit == {"Income"} and debit and debit <= set(ASSET_LIKE):
        return "income"
    if credit and debit and credit <= set(ASSET_LIKE) and debit <= set(ASSET_LIKE):
        return "transfer"
    return "other"


def named_person(person: UUID | None, kind: str) -> tuple[UUID | None, str]:
    """The person an expense or income names as its payee (the `@` in the payee field), and which way the gift went."""
    if person is None:
        return None, "sent"
    if kind not in ("expense", "income"):
        raise ValueError("a person can be named on an expense or an income only: use a transfer to lend or borrow!")
    return person, "sent" if kind == "expense" else "received"


def person_transfer(people: set[UUID], rows: list[EntryRow], form: EntryForm) -> tuple[UUID, TransferCreate]:
    """The loan or borrowing the form describes: one person and one of your accounts, one amount. A person on the To side
    is money lent to them, on the From side money borrowed from them."""
    mine = [r for r in rows if r.choice not in people]
    theirs = [r for r in rows if r.choice in people]
    if len(rows) != 2 or len(theirs) != 1 or len(mine) != 1 or theirs[0].side == mine[0].side:
        raise ValueError("a person goes on one side, one of your accounts on the other, for one amount!")
    if theirs[0].amount != mine[0].amount:
        raise ValueError("the amount to or from a person must be the same on both sides!")
    sent = theirs[0].side == PostingSide.DEBIT  # the money goes to them
    data: dict[str, object] = {
        "direction": "sent" if sent else "received",
        "purpose": "loan" if sent else "borrowing",
        "amount": theirs[0].amount,
        "account_id": mine[0].choice,
        "description": (form.comment or "").strip() or None,
    }
    if form.date:
        data["date"] = form.date  # without one, the transfer is dated today
    return theirs[0].choice, TransferCreate.model_validate(data)


def postings_of(rows: list[EntryRow], places: Mapping[UUID, UUID]) -> list[PostingCreate]:
    """The rows as postings: a row whose choice is a category (a key of `places`: category id -> the Expenses or Income
    account it posts to) is a line on that account labelled with the category."""
    return [
        PostingCreate(
            account_id=places.get(row.choice, row.choice),
            side=row.side,
            amount=row.amount,
            category_id=row.choice if row.choice in places else row.category_id,
            posted_on=row.posted_on,
        )
        for row in rows
    ]


class EntryService:
    def __init__(
        self,
        transactions: TransactionService,
        accounts: AccountService,
        categories: CategoryService,
        contacts: ContactService,
        transfers: TransferService,
        expenses: ExpenseSharingService,
        incomes: IncomeSharingService,
    ):
        self.transactions = transactions
        self.accounts = accounts
        self.categories = categories
        self.contacts = contacts
        self.transfers = transfers
        self.expenses = expenses
        self.incomes = incomes

    def roots(self) -> dict[UUID, str]:
        """Each account's top-level account (Assets, Expenses…), by id."""
        return {n.account.id: r.account.name for r in build_tree(self.accounts.list()) for n in r.walk()}

    def category_places(self) -> dict[UUID, UUID]:
        """Where a line labelled with each category posts: the Expenses account for a spending one, Income for an
        earning one."""
        roots = {a.name: a.id for a in self.accounts.list() if a.parent_id is None}
        return {
            c.id: roots["Expenses" if c.kind == "spending" else "Income"]
            for c in self.categories.list(include_closed=True)
        }

    def postings(self, rows: list[EntryRow]) -> list[PostingCreate]:
        return postings_of(rows, self.category_places())

    def _people(self) -> set[UUID]:
        return {c.id for c in self.contacts.people()} if self.contacts.has_people() else set()

    def create(self, form: EntryForm) -> EntrySaved:
        """Record a new entry. Nothing is kept when any part of it is refused."""
        people = self._people()
        try:
            if people & {r.choice for r in form.rows}:
                if form.tags or form.related_id:
                    raise ValueError("tags and related entries are not available for money moved to or from a person!")
                person, data = person_transfer(people, form.rows, form)
                return EntrySaved(transaction_id=self.transfers.move(person, data), recorded="transfer")
            gift, way = named_person(form.payee_contact, form.kind)
            entry = self.transactions.create(
                TransactionCreate(
                    date=form.date or local_today(),
                    payee=(form.payee or "").strip() or None,
                    comment=(form.comment or "").strip() or None,
                    postings=self.postings(form.rows),
                    related_id=form.related_id,
                    tags=form.tags,
                ),
                commit=False,
            )
            if gift is not None:
                self.transfers.name_gift(entry.id, gift, way)
            self.transactions.save()
            return EntrySaved(transaction_id=entry.id, recorded="transaction")
        except ValidationError as e:
            self.transactions.discard()
            raise ValueError(validation_message(e)) from None
        except Exception:
            self.transactions.discard()
            raise

    def release(self, transaction_id: UUID, purposes: set[str], keep: str) -> None:
        """Before an entry made through people is saved as something else, what it was goes: a loan or borrowing, a bill
        shared with people, or income shared with people. `keep` names what it is about to become when that replaces the
        old records itself ("loan", "bill" or "income"). Anything else a person made is not edited here. The caller rolls
        back if what follows fails."""
        if not purposes:
            return
        if purposes == {"expense"}:
            if keep != "bill":
                self.expenses.detach(transaction_id)
        elif purposes == {"income"}:
            if keep != "income":
                self.incomes.detach(transaction_id)
        elif purposes <= {"loan", "borrowing"}:
            if keep != "loan":
                self.transfers.detach(transaction_id)
        else:
            raise ValueError(
                "only a loan, a borrowing, or a bill or income shared with people can be changed here: use the "
                "person's page!"
            )

    def update(self, transaction_id: UUID, form: EntryForm) -> EntrySaved:
        """Change an entry into what the form now says, releasing what it was first; all of it or nothing."""
        people = self._people()
        purposes = {r.purpose for r in self.contacts.made_of(transaction_id)}
        try:
            if people & {r.choice for r in form.rows}:
                # A person on one side of a transfer: the entry becomes (or stays) a loan or a borrowing, in place.
                self.release(transaction_id, purposes, "loan")
                person, loan = person_transfer(people, form.rows, form)
                self.transfers.convert(transaction_id, person, loan, form.tags, form.related_id)
                return EntrySaved(transaction_id=transaction_id, recorded="transfer")
            self.release(transaction_id, purposes, "")  # edited back into an ordinary entry
            gift, way = named_person(form.payee_contact, form.kind)
            if gift is not None or self.transfers.gift_of(transaction_id) is not None:
                self.transfers.name_gift(transaction_id, gift, way)  # saved with the entry below
            changes: dict[str, object] = {
                "payee": (form.payee or "").strip() or None,
                "comment": (form.comment or "").strip() or None,
                "postings": self.postings(form.rows),
                "related_id": form.related_id,
                "tags": form.tags,
            }
            if form.date:
                changes["date"] = form.date  # without one, the entry keeps its own
            self.transactions.update(transaction_id, TransactionUpdate.model_validate(changes))
            return EntrySaved(transaction_id=transaction_id, recorded="transaction")
        except ValidationError as e:
            self.transactions.discard()
            raise ValueError(validation_message(e)) from None
        except ValueError as e:
            self.transactions.discard()
            if "not found" in str(e) and f"'{transaction_id}'" in str(e):
                raise LookupError("transaction not found") from None
            raise
        except Exception:
            self.transactions.discard()
            raise
