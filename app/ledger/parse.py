"""Parser for the common subset of the ledger / hledger journal format.

finode keeps one currency, so conversions (`@` / `@@` prices) and `P` price lines are errors, and an
amount may carry a label ("INR", "$") that the importer checks against the person's currency. Anything
finode cannot represent faithfully (lots, virtual postings, automated or periodic transactions,
includes, balance assignments, prices) is reported as an error with its line number instead of being
silently dropped.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast

from .model import AccountDecl, Journal, LedgerPosting, LedgerTransaction

COMMENT_STARTS = ";#%|*"
# Directives that carry nothing finode needs; their indented lines are skipped too.
IGNORED_DIRECTIVES = {"payee", "tag", "D", "N", "default"}

DATE = r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
HEADER = re.compile(rf"^{DATE}(?:=(?:\d{{4}}[-/.])?\d{{1,2}}[-/.]\d{{1,2}})?(?P<rest>(?:\s.*)?)$")
INLINE_COMMENT = re.compile(r"\s;")
NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
SYMBOL = r"\"[^\"]+\"|[^\d\s+\-\"=@{(;]+"
AMOUNT = re.compile(rf"^(?P<s1>[-+])?\s*(?P<pre>{SYMBOL})?\s*(?P<s2>[-+])?\s*(?P<num>{NUMBER})\s*(?P<post>{SYMBOL})?$")
MAX_PLACES = 8


def _plain(value: Decimal) -> str:
    """An amount without exponent, with at least two decimals: 5 -> 5.00, 0.0125 -> 0.0125."""
    exponent = value.normalize().as_tuple().exponent
    places = max(2, -exponent) if isinstance(exponent, int) else 2
    return format(value.quantize(Decimal(1).scaleb(-places)), "f")


@dataclass
class _Entry:
    number: int
    account: str
    amount: Decimal | None
    commodity: str | None
    assertion: Decimal | None = None
    assertion_commodity: str | None = None


class _State:
    def __init__(self) -> None:
        self.journal = Journal()
        self.balances: dict[tuple[str, str | None], Decimal] = {}

    def error(self, line: int, message: str) -> None:
        self.journal.errors.append(f"line {line}: {message}")


def _parse_amount(text: str, state: _State, line: int) -> tuple[Decimal, str | None] | None:
    match = AMOUNT.match(text.strip())
    if not match:
        state.error(line, f"cannot read the amount '{text.strip()}'")
        return None
    symbol = (match["pre"] or match["post"] or "").strip('"') or None
    try:
        amount = Decimal(match["num"].replace(",", ""))
    except InvalidOperation:
        state.error(line, f"cannot read the amount '{text.strip()}'")
        return None
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > MAX_PLACES:
        state.error(line, f"'{text.strip()}' has more than {MAX_PLACES} decimal places")
        return None
    negative = "-" in (match["s1"] or "") + (match["s2"] or "")
    return (-amount if negative else amount), symbol


def _split_comment(text: str) -> tuple[str, str | None]:
    parts = INLINE_COMMENT.split(text, maxsplit=1)
    if len(parts) == 1:
        return text, None
    return parts[0], parts[1].strip() or None


def _parse_entry(number: int, raw: str, state: _State) -> _Entry | None:
    body, _ = _split_comment(raw.strip())
    body = re.sub(r"^[*!]\s+", "", body.strip())
    if body.startswith(("(", "[")):
        state.error(number, "virtual postings are not supported")
        return None
    parts = re.split(r"\t|\s{2,}", body, maxsplit=1)
    account = parts[0].strip()
    amount_text = parts[1].strip() if len(parts) > 1 else ""
    if "{" in amount_text:
        state.error(number, "lots are not supported")
        return None
    amount_text, equals, assertion_text = amount_text.partition("=")
    if "@" in amount_text:
        state.error(number, "conversions between currencies are not supported: finode keeps one currency")
        return None

    entry = _Entry(number, account, None, None)
    if amount_text.strip():
        parsed = _parse_amount(amount_text, state, number)
        if parsed is None:
            return None
        entry.amount, entry.commodity = parsed
    elif equals:
        state.error(number, "balance assignments are not supported")
        return None
    if equals:
        asserted = _parse_amount(assertion_text.lstrip("=* "), state, number)
        if asserted is None:
            return None
        entry.assertion, entry.assertion_commodity = asserted
    return entry


def _parse_transaction(header: re.Match, block: list[tuple[int, str]], line: int, state: _State) -> None:
    try:
        when = date(int(header[1]), int(header[2]), int(header[3]))
    except ValueError:
        state.error(line, "not a valid date")
        return

    rest, comment = _split_comment(header["rest"].strip())
    rest = re.sub(r"^[*!](\s+|$)", "", rest)
    rest = re.sub(r"^\([^)]*\)(\s+|$)", "", rest).strip()
    notes = [comment] if comment else []

    entries: list[_Entry] = []
    failed = False
    for number, raw in block:
        body = raw.strip()
        if body.startswith(";"):
            if not entries and body.lstrip("; ").strip():
                notes.append(body.lstrip("; ").strip())
            continue
        entry = _parse_entry(number, raw, state)
        if entry is None:
            failed = True
        else:
            entries.append(entry)

    if failed:
        return
    if len(entries) < 2:
        state.error(line, "a transaction needs at least two postings")
        return
    elided = [e for e in entries if e.amount is None]
    if len(elided) > 1:
        state.error(elided[1].number, "only one posting may leave out its amount")
        return

    # Labels ("INR", "$") are not told apart here: the importer checks that they are the person's currency.
    total = sum((e.amount for e in entries if e.amount is not None), Decimal(0))
    if elided:
        labels = {e.commodity for e in entries if e.amount is not None and e.commodity is not None}
        elided[0].amount, elided[0].commodity = -total, (next(iter(labels)) if len(labels) == 1 else None)
    elif total != 0:
        state.error(line, f"does not balance (off by {_plain(abs(total))})")
        return

    postings = []
    running = dict(state.balances)
    for entry in entries:
        amount = cast(Decimal, entry.amount)  # the one that left its amount out was filled in above
        key = (entry.account, entry.assertion_commodity or entry.commodity)
        running[key] = running.get(key, Decimal(0)) + amount
        if entry.assertion is not None and running[key] != entry.assertion:
            state.error(
                entry.number,
                f"balance assertion failed: '{entry.account}' is {_plain(running[key])}, expected {_plain(entry.assertion)}",
            )
            return
        postings.append(
            LedgerPosting(
                account=entry.account,
                amount=amount,
                line=entry.number,
                commodity=entry.commodity,
            )
        )
    state.balances = running
    state.journal.transactions.append(LedgerTransaction(when, rest, notes, postings, line))


def _parse_directive(raw: str, block: list[tuple[int, str]], line: int, state: _State) -> None:
    word = raw.split(None, 1)[0]
    rest = raw[len(word) :].strip()
    if word == "account":
        name, note = _split_comment(rest)
        for _, sub in block:
            keyword, _, value = sub.strip().partition(" ")
            if keyword == "note" and value.strip():
                note = value.strip()
        state.journal.accounts.append(AccountDecl(name.strip(), note, line))
    elif word == "commodity":
        return  # how a currency is written: nothing finode needs
    elif word == "P":
        state.error(line, "prices are not supported: finode keeps one currency")
    elif word == "decimal-mark":
        if rest != ".":
            state.error(line, "only '.' as the decimal mark is supported")
    elif word in IGNORED_DIRECTIVES:
        return
    elif word[0] in "=~":
        state.error(line, "automated and periodic transactions are not supported")
    else:
        state.error(line, f"unsupported directive '{word}'")


def parse(text: str) -> Journal:
    lines = text.splitlines()
    state = _State()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = i + 1
        i += 1
        if not raw.strip() or raw[0] in COMMENT_STARTS:
            continue
        if raw[0] in " \t":
            if not raw.strip().startswith(";"):
                state.error(line, "unexpected indented line")
            continue
        block: list[tuple[int, str]] = []
        while i < len(lines) and lines[i] and lines[i][0] in " \t":
            block.append((i + 1, lines[i]))
            i += 1
        header = HEADER.match(raw.rstrip())
        if header:
            _parse_transaction(header, block, line, state)
        elif raw[0].isdigit():
            state.error(line, "cannot read the transaction date")
        else:
            _parse_directive(raw.rstrip(), block, line, state)
    return state.journal
