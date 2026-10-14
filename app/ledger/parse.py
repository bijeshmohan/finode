"""Parser for the common subset of the ledger / hledger journal format.

Several commodities are read, including conversions written with `@` / `@@` prices and
`P` price lines. Anything finode cannot represent faithfully (lots, virtual postings,
automated or periodic transactions, includes, balance assignments) is reported as an
error with its line number instead of being silently dropped.
"""
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from .model import AccountDecl, CommodityDecl, Journal, LedgerPosting, LedgerTransaction, PriceDecl


COMMENT_STARTS = ";#%|*"
# Directives that carry nothing finode needs; their indented lines are skipped too.
IGNORED_DIRECTIVES = {"payee", "tag", "D", "N", "default"}

DATE = r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
HEADER = re.compile(rf"^{DATE}(?:=(?:\d{{4}}[-/.])?\d{{1,2}}[-/.]\d{{1,2}})?(?P<rest>(?:\s.*)?)$")
INLINE_COMMENT = re.compile(r"\s;")
NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
SYMBOL = r"\"[^\"]+\"|[^\d\s+\-\"=@{(;]+"
AMOUNT = re.compile(
    rf"^(?P<s1>[-+])?\s*(?P<pre>{SYMBOL})?\s*(?P<s2>[-+])?\s*(?P<num>{NUMBER})\s*(?P<post>{SYMBOL})?$"
)
PRICE_LINE = re.compile(
    rf"^{DATE}(?:\s+\d{{1,2}}:\d{{2}}(?::\d{{2}})?)?\s+(?P<symbol>\"[^\"]+\"|\S+)\s+(?P<price>.+)$"
)
TAG = re.compile(r"(\w+):\s*([^,]+)")
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
    cost: Decimal | None = None
    cost_commodity: str | None = None
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
    if -amount.as_tuple().exponent > MAX_PLACES:
        state.error(line, f"'{text.strip()}' has more than {MAX_PLACES} decimal places")
        return None
    negative = "-" in (match["s1"] or "") + (match["s2"] or "")
    return (-amount if negative else amount), symbol


def _split_comment(text: str) -> tuple[str, str | None]:
    parts = INLINE_COMMENT.split(text, maxsplit=1)
    if len(parts) == 1:
        return text, None
    return parts[0], parts[1].strip() or None


def _split_cost(text: str) -> tuple[str, str | None, bool]:
    """('100 USD', '8350 INR', total) for '100 USD @@ 8350 INR'; '@' is a price per unit."""
    found = re.search(r"@@|@", text)
    if not found:
        return text, None, False
    return text[: found.start()], text[found.end():], found.group() == "@@"


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
    amount_text, cost_text, per_total = _split_cost(amount_text)

    entry = _Entry(number, account, None, None)
    if amount_text.strip():
        parsed = _parse_amount(amount_text, state, number)
        if parsed is None:
            return None
        entry.amount, entry.commodity = parsed
    elif equals:
        state.error(number, "balance assignments are not supported")
        return None
    if cost_text is not None:
        if entry.amount is None:
            state.error(number, "a price needs an amount")
            return None
        priced = _parse_amount(cost_text, state, number)
        if priced is None:
            return None
        price, entry.cost_commodity = priced
        if price <= 0:
            state.error(number, "a price must be positive")
            return None
        entry.cost = price if per_total else abs(entry.amount) * price
    if equals:
        asserted = _parse_amount(assertion_text.lstrip("=* "), state, number)
        if asserted is None:
            return None
        entry.assertion, entry.assertion_commodity = asserted
    return entry


def _balance_key(entry: _Entry) -> tuple[str | None, Decimal]:
    """What the posting contributes to balancing: its cost when it was converted, else its amount."""
    if entry.cost is not None:
        return entry.cost_commodity, entry.cost if entry.amount >= 0 else -entry.cost
    return entry.commodity, entry.amount


def _balance_groups(entries: list[_Entry]) -> dict[str | None, Decimal]:
    groups: dict[str | None, Decimal] = {}
    for entry in entries:
        if entry.amount is not None:
            commodity, amount = _balance_key(entry)
            groups[commodity] = groups.get(commodity, Decimal(0)) + amount
    # An amount written without a commodity belongs to the only commodity the transaction has.
    named = [c for c in groups if c is not None]
    if None in groups and len(named) == 1:
        groups[named[0]] += groups.pop(None)
    return groups


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

    groups = _balance_groups(entries)
    off = {commodity: total for commodity, total in groups.items() if total != 0}
    if elided:
        if len(off) > 1:
            state.error(line, _mixed(off))
            return
        commodity, total = next(iter(off.items()), (None, Decimal(0)))
        elided[0].amount, elided[0].commodity = -total, commodity
    elif off:
        if len([c for c in groups if c is not None]) > 1:
            state.error(line, _mixed(off))
        else:
            state.error(line, f"does not balance (off by {_plain(sum(abs(t) for t in off.values()))})")
        return

    postings = []
    running = dict(state.balances)
    for entry in entries:
        key = (entry.account, entry.assertion_commodity or entry.commodity)
        running[key] = running.get(key, Decimal(0)) + entry.amount
        if entry.assertion is not None and running[key] != entry.assertion:
            state.error(
                entry.number,
                f"balance assertion failed: '{entry.account}' is {_plain(running[key])}, expected {_plain(entry.assertion)}",
            )
            return
        postings.append(
            LedgerPosting(
                account=entry.account,
                amount=entry.amount,
                line=entry.number,
                commodity=entry.commodity,
                cost=entry.cost,
                cost_commodity=entry.cost_commodity,
            )
        )
    state.balances = running
    state.journal.transactions.append(LedgerTransaction(when, rest, notes, postings, line))


def _mixed(off: dict[str | None, Decimal]) -> str:
    names = " and ".join(f"'{c or 'no commodity'}'" for c in off)
    return (
        f"mixes currencies ({names}) without a price: write the conversion on the posting "
        "that was bought or sold, like '100 USD @@ 8350 INR'"
    )


def _tags(comment: str | None) -> dict[str, str]:
    return {key.lower(): value.strip() for key, value in TAG.findall(comment or "")}


def _parse_commodity(rest: str, block: list[tuple[int, str]], line: int, state: _State) -> None:
    body, comment = _split_comment(rest)
    body = body.strip()
    symbol, decimals = body.strip('"'), None
    if re.search(r"\d", body):
        parsed = AMOUNT.match(body)
        if not parsed:
            state.error(line, f"cannot read the commodity '{body}'")
            return
        symbol = (parsed["pre"] or parsed["post"] or "").strip('"')
        decimals = len(parsed["num"].partition(".")[2])
    tags = _tags(comment)
    for _, sub in block:
        keyword, _, value = sub.strip().partition(" ")
        if keyword == "format":
            formatted = AMOUNT.match(value.strip())
            if formatted:
                symbol = symbol or (formatted["pre"] or formatted["post"] or "").strip('"')
                decimals = len(formatted["num"].partition(".")[2])
        elif keyword == "note":
            tags.update(_tags(value))
    if not symbol:
        state.error(line, "a commodity directive needs a commodity")
        return
    state.journal.commodities.append(
        CommodityDecl(symbol, decimals, tags.get("name"), (tags.get("kind") or "").lower() or None, line)
    )


def _parse_price(rest: str, line: int, state: _State) -> None:
    found = PRICE_LINE.match(rest.strip())
    if not found:
        state.error(line, "cannot read the price line")
        return
    try:
        when = date(int(found[1]), int(found[2]), int(found[3]))
    except ValueError:
        state.error(line, "not a valid date")
        return
    priced = _parse_amount(found["price"], state, line)
    if priced is None:
        return
    price, quote = priced
    if price <= 0:
        state.error(line, "a price must be positive")
        return
    state.journal.prices.append(PriceDecl(when, found["symbol"].strip('"'), price, quote, line))


def _parse_directive(raw: str, block: list[tuple[int, str]], line: int, state: _State) -> None:
    word = raw.split(None, 1)[0]
    rest = raw[len(word):].strip()
    if word == "account":
        name, note = _split_comment(rest)
        for _, sub in block:
            keyword, _, value = sub.strip().partition(" ")
            if keyword == "note" and value.strip():
                note = value.strip()
        state.journal.accounts.append(AccountDecl(name.strip(), note, line))
    elif word == "commodity":
        _parse_commodity(rest, block, line, state)
    elif word == "P":
        _parse_price(rest, line, state)
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
