"""What the People pages show and do: the list with each person's quiet line, a person's open amounts and activity with
what each is called, an entry's sheet, reversing an entry the way its kind is reversed, and adding a person with an
opening balance all or nothing. The web pages (routers/web/people.py) and the finode app's views (/api/views/people…)
both go through here."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from pydantic import ValidationError

from ..schemas.contact import ActivityRead, ContactCreate, ContactRead, ObligationRead
from .contact import ContactService
from .contact_summary import ContactSummaryService
from .expense_sharing import ExpenseSharingService
from .income_sharing import IncomeSharingService
from .obligation import ObligationService
from .settlement import SettlementService
from .transfer import TransferService

# How an amount is written in the person's currency (templating.money with their grouping).
Money = Callable[[Decimal], str]

SHOWS = {"all": "All", "owed": "Owe you", "owe": "You owe"}
SOURCE_NAMES = {"loan": "Loan", "borrowing": "Borrowed", "advance": "Advance", "opening": "Opening balance"}
# How many of a person's entries their page lists.
ACTIVITY_SHOWN = 30


@dataclass
class PersonRow:
    person: ContactRead
    sub: str


Show = Literal["all", "owed", "owe", "archived"]


@dataclass
class PeoplePage:
    show: Show
    rows: list[PersonRow]
    has_archived: bool
    owed_total: Decimal
    owe_total: Decimal
    # Whether there is anyone not archived.
    everyone: bool

    @property
    def label(self) -> str:
        """What the head says: which way more is owed (owed to you wins a tie), or that nothing is."""
        if not (self.owed_total or self.owe_total):
            return "Everything is settled"
        return "Owed to you" if self.owed_total >= self.owe_total else "You owe"


def person_sub(p: ContactRead, money: Money) -> str:
    """The quiet line under a person on the list."""
    if p.archived:
        return "Archived"
    if p.last_activity is None:
        return "Nothing yet"
    if p.net == 0 and p.receivable == 0 and p.payable == 0:
        return "Settled up"
    if p.net == 0:
        return f"Even · {money(p.receivable)} each way"
    return f"Last {p.last_activity.strftime('%d %b').lstrip('0')}"


def people_page(contacts: ContactService, show: str, money: Money) -> PeoplePage:
    shown = cast(Show, show) if show in (*SHOWS, "archived") else "all"
    everyone = contacts.list(include_archived=True)
    live = [p for p in everyone if not p.archived]
    if shown == "archived":
        chosen = [p for p in everyone if p.archived]
    elif shown == "owed":
        chosen = [p for p in live if p.receivable > 0]
    elif shown == "owe":
        chosen = [p for p in live if p.payable > 0]
    else:
        chosen = live
    return PeoplePage(
        show=shown,
        rows=[PersonRow(p, person_sub(p, money)) for p in chosen],
        has_archived=any(p.archived for p in everyone),
        owed_total=sum((p.receivable for p in live), Decimal(0)),
        owe_total=sum((p.payable for p in live), Decimal(0)),
        everyone=bool(live),
    )


def describe_obligation(o: ObligationRead) -> tuple[str, str]:
    """What an open amount is called, and who owes whom."""
    name = o.description or SOURCE_NAMES.get(o.source_type, "Shared expense")
    return name, "they owe you" if o.direction == "receivable" else "you owe them"


def entry_title(item: ActivityRead) -> str:
    """What an entry done with a person is called on their page and in its sheet."""
    names = {
        "loan": "Loan",
        "borrowing": "Borrowed",
        "advance": "Advance",
        "gift": "Gift",
        "opening": "Opening balance",
        "netoff": "Evened out",
        "income": item.description or "Shared income",
        "expense": item.description or "Shared expense",
        "settlement": "Paid back" if item.direction == "received" else "You paid back",
    }
    return names[item.purpose]


def entry_detail(item: ActivityRead) -> str | None:
    """What follows the day on an entry's line: whose share or part it is, or its note."""
    if item.purpose == "expense":
        return "their share"
    if item.purpose == "income":
        return "their part" if item.direction == "received" else "received for you"
    return item.description or None


@dataclass
class OpenRow:
    obligation: ObligationRead
    name: str
    who: str
    # Part of it has been paid back.
    partly: bool


@dataclass
class ActivityRow:
    item: ActivityRead
    title: str
    detail: str | None
    # Money that came to you: a settlement they paid or a gift they gave.
    income: bool


@dataclass
class PersonPage:
    person: ContactRead
    open: list[OpenRow]
    activity: list[ActivityRow]
    more_activity: int

    @property
    def both_ways(self) -> bool:
        """Owed both ways at once (only for a moment, until it evens out): each open row then says which way."""
        return bool(self.person.receivable and self.person.payable)


def person_page(
    contact_id: UUID, contacts: ContactService, obligations: ObligationService, summaries: ContactSummaryService
) -> PersonPage:
    """One person's page. LookupError for someone who is not the person's."""
    person = contacts.read(contact_id)
    if person is None:
        raise LookupError("person not found")
    rows = []
    for o in obligations.list(contact_id, open_only=True):
        name, who = describe_obligation(o)
        rows.append(OpenRow(o, name, who, o.settled_amount > 0))
    found = summaries.activity(contact_id, limit=ACTIVITY_SHOWN)
    return PersonPage(
        person=person,
        open=rows,
        activity=[
            ActivityRow(
                a,
                entry_title(a),
                entry_detail(a),
                a.direction == "received" and a.purpose in ("settlement", "gift"),
            )
            for a in found.items
        ],
        more_activity=found.total - len(found.items),
    )


@dataclass
class EntrySheet:
    person: ContactRead
    item: ActivityRead
    title: str
    # The lines under the title, in order.
    notes: list[str]
    # An opening balance can be edited; everything but an evened-out entry can be reversed.
    can_edit: bool
    can_reverse: bool


def entry_notes(item: ActivityRead, name: str) -> list[str]:
    notes = []
    if item.description and item.purpose not in ("expense", "income"):
        notes.append(item.description)
    if item.purpose == "expense":
        notes.append(f"{name}'s share of the bill.")
    if item.purpose == "income":
        notes.append(
            f"{name}'s part of what came in: you hold it for them."
            if item.direction == "received"
            else f"What {name} received for you."
        )
    if item.purpose == "netoff":
        notes.append(
            "What each owed the other was cleared against each other. It goes by itself if one of them is undone."
        )
    return notes


def entry_sheet(
    contact_id: UUID, transaction_id: UUID, contacts: ContactService, summaries: ContactSummaryService
) -> EntrySheet:
    """One entry of a person's in its sheet. LookupError for a person or an entry that is not theirs."""
    person = contacts.read(contact_id)
    item = summaries.entry(contact_id, transaction_id) if person is not None else None
    if person is None or item is None:
        raise LookupError("entry not found")
    return EntrySheet(
        person=person,
        item=item,
        title=entry_title(item),
        notes=entry_notes(item, person.name),
        can_edit=item.purpose == "opening",
        can_reverse=item.purpose != "netoff",
    )


def reverse(
    item: ActivityRead,
    settlements: SettlementService,
    incomes: IncomeSharingService,
    expenses: ExpenseSharingService,
    transfers: TransferService,
) -> None:
    """Undo an entry done with a person, for good, the way its kind is undone. ValueError (or the services' own
    conflict) when it cannot be: something was paid back against it."""
    if item.purpose == "settlement":
        settlements.reverse(item.transaction_id)
    elif item.purpose == "income":
        incomes.cancel(item.transaction_id)
    elif item.purpose == "expense":
        expense = expenses.of_entry(item.transaction_id)
        if expense is None:
            raise ValueError("shared expense not found!")
        expenses.cancel(expense.id)
    elif item.purpose == "netoff":
        raise ValueError("an evened-out entry goes by itself when one of the two is undone!")
    else:
        transfers.reverse(item.transaction_id)


def add_person(contacts: ContactService, transfers: TransferService, data: ContactCreate) -> ContactRead:
    """Add a person and, with `opening`, what they already owed: both or neither."""
    made = contacts.create(data)
    if data.opening is None:
        return made
    try:
        transfers.opening_balance(made.id, data.opening)
    except ValueError, ValidationError:
        contacts.delete(made.id)  # nothing else was done with them: they are removed again, not left half made
        raise
    found = contacts.read(made.id)
    return found if found is not None else made
