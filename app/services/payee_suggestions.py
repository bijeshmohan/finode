"""The chips under the Add screen's payee field: names of people you pay, or after an "@" your people. Only names are
suggested, never accounts or categories (see docs/developer/reference/ui-pages.md, the Add screen)."""

from ..schemas.transaction import PayeeSuggestions, PersonChip
from .contact import ContactService
from .transaction import TransactionService

SUGGESTED_PAYEES = 6  # how many chips sit under the payee field
SUGGESTED_PEOPLE = 8  # how many people sit under the payee field after an "@"


def suggested_payees(names: list[str], query: str = "", limit: int = SUGGESTED_PAYEES) -> list[str]:
    """The chips while something is typed, from the people paid most (`names` come most used first): those starting
    with it, then containing it, an exact match first; nothing for an empty field."""
    wanted = query.strip().lower()
    if not wanted:
        return []
    exact = [n for n in names if n.lower() == wanted]
    starting = [n for n in names if n.lower().startswith(wanted) and n.lower() != wanted]
    containing = [n for n in names if wanted in n.lower() and not n.lower().startswith(wanted)]
    return (exact + starting + containing)[:limit]


def suggest(transactions: TransactionService, contacts: ContactService, payee: str, only: str = "") -> PayeeSuggestions:
    """People you pay that match what is typed, the ones paid most first. After an "@", your people instead (the entry
    will name the person, nothing is owed), A to Z, those starting with it first. `only="people"` (editing an entry)
    offers people only: the payee it has is not second-guessed."""
    if payee.startswith("@"):
        wanted = payee[1:].strip().casefold()
        found = [c for c in contacts.people() if c.archived_at is None and wanted in c.name.casefold()]
        found.sort(key=lambda c: (not c.name.casefold().startswith(wanted), c.name.casefold()))
        return PayeeSuggestions(people=[PersonChip(id=c.id, name=c.name) for c in found[:SUGGESTED_PEOPLE]])
    if only == "people":
        return PayeeSuggestions()
    return PayeeSuggestions(names=suggested_payees([name for name, _ in transactions.payees()], payee))
