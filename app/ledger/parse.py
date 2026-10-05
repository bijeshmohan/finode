"""Parser for the common subset of the ledger / hledger journal format.

Anything finode cannot represent faithfully (several currencies, prices, virtual
postings, automated or periodic transactions, includes) is reported as an error
with its line number instead of being silently dropped.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from .model import AccountDecl, Journal, LedgerPosting, LedgerTransaction


COMMENT_STARTS = ";#%|*"
# Directives that carry nothing finode needs; their indented lines are skipped too.
IGNORED_DIRECTIVES = {"commodity", "payee", "tag", "P", "D", "N", "default"}

DATE = r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
HEADER = re.compile(rf"^{DATE}(?:=(?:\d{{4}}[-/.])?\d{{1,2}}[-/.]\d{{1,2}})?(?P<rest>(?:\s.*)?)$")
INLINE_COMMENT = re.compile(r"\s;")
NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
SYMBOL = r"\"[^\"]+\"|[^\d\s+\-\"=@{(;]+"
AMOUNT = re.compile(
    rf"^(?P<s1>[-+])?\s*(?P<pre>{SYMBOL})?\s*(?P<s2>[-+])?\s*(?P<num>{NUMBER})\s*(?P<post>{SYMBOL})?$"
)
TWO_PLACES = Decimal("0.01")


class _State:
    def __init__(self) -> None:
        self.journal = Journal()
        self.commodity: str | None = None
        self.balances: dict[str, Decimal] = {}

    def error(self, line: int, message: str) -> None:
        self.journal.errors.append(f"line {line}: {message}")


def _parse_amount(text: str, state: _State, line: int) -> Decimal | None:
    match = AMOUNT.match(text.strip())
    if not match:
        state.error(line, f"cannot read the amount '{text.strip()}'")
        return None
    symbol = (match["pre"] or match["post"] or "").strip('"')
    if symbol:
        if state.commodity is None:
            state.commodity = symbol
        elif state.commodity != symbol:
            state.error(line, f"mixes currencies ('{state.commodity}' and '{symbol}'); finode keeps one currency")
            return None
    try:
        amount = Decimal(match["num"].replace(",", ""))
        if amount != amount.quantize(TWO_PLACES):
            state.error(line, f"'{text.strip()}' has more than 2 decimal places")
            return None
        amount = amount.quantize(TWO_PLACES)
    except InvalidOperation:
        state.error(line, f"cannot read the amount '{text.strip()}'")
        return None
    return -amount if "-" in (match["s1"] or "") + (match["s2"] or "") else amount


def _split_comment(text: str) -> tuple[str, str | None]:
    parts = INLINE_COMMENT.split(text, maxsplit=1)
    if len(parts) == 1:
        return text, None
    return parts[0], parts[1].strip() or None


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

    entries: list[tuple[int, str, Decimal | None, Decimal | None]] = []
    failed = False
    for number, raw in block:
        body = raw.strip()
        if body.startswith(";"):
            if not entries and body.lstrip("; ").strip():
                notes.append(body.lstrip("; ").strip())
            continue
        body, _ = _split_comment(body)
        body = re.sub(r"^[*!]\s+", "", body.strip())
        if body.startswith(("(", "[")):
            state.error(number, "virtual postings are not supported")
            failed = True
            continue
        parts = re.split(r"\t|\s{2,}", body, maxsplit=1)
        account = parts[0].strip()
        amount_text = parts[1].strip() if len(parts) > 1 else ""
        if re.search(r"@|\{", amount_text):
            state.error(number, "prices, costs and lots are not supported")
            failed = True
            continue
        amount_text, equals, assertion_text = amount_text.partition("=")
        amount = assertion = None
        if amount_text.strip():
            amount = _parse_amount(amount_text, state, number)
            if amount is None:
                failed = True
                continue
        elif equals:
            state.error(number, "balance assignments are not supported")
            failed = True
            continue
        if equals:
            assertion = _parse_amount(assertion_text.lstrip("=* "), state, number)
            if assertion is None:
                failed = True
                continue
        entries.append((number, account, amount, assertion))

    if failed:
        return
    if len(entries) < 2:
        state.error(line, "a transaction needs at least two postings")
        return
    elided = [e for e in entries if e[2] is None]
    if len(elided) > 1:
        state.error(elided[1][0], "only one posting may leave out its amount")
        return
    total = sum((e[2] for e in entries if e[2] is not None), Decimal("0.00"))
    if not elided and total != 0:
        state.error(line, f"does not balance (off by {abs(total):.2f})")
        return

    postings = []
    running = dict(state.balances)
    for number, account, amount, assertion in entries:
        if amount is None:
            amount = -total
        running[account] = running.get(account, Decimal("0.00")) + amount
        if assertion is not None and running[account] != assertion:
            state.error(number, f"balance assertion failed: '{account}' is {running[account]:.2f}, expected {assertion:.2f}")
            return
        postings.append(LedgerPosting(account=account, amount=amount, line=number))
    state.balances = running
    state.journal.transactions.append(LedgerTransaction(when, rest, notes, postings, line))


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
