"""Export to and import from the ledger journal format (and CSV for spreadsheets)."""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError

from ..ledger import AccountDecl, CommodityDecl, LedgerPosting, LedgerTransaction, PriceDecl, parse, write
from ..ledger.parse import _plain
from ..models.commodity import Commodity, CommodityKind
from ..models.transaction import PostingSide
from ..repositories import AccountRepository, ProfileRepository, TransactionRepository
from ..schemas.account import AccountCreate
from ..schemas.commodity import CODE_PATTERN
from ..schemas.data import ImportSummary
from ..schemas.transaction import PostingCreate, TransactionCreate
from .account import GROUP_POSTING_ROOT_NAMES, OPENING_BALANCES_ACCOUNT_NAME, AccountService
from .depth import depth_limits


MAX_REPORTED_ERRORS = 20
ROOT_ALIASES = {
    "assets": "Assets", "asset": "Assets",
    "liabilities": "Liabilities", "liability": "Liabilities",
    "equity": "Equity",
    "income": "Income", "revenue": "Income", "revenues": "Income",
    "expenses": "Expenses", "expense": "Expenses",
}
OPENING_BALANCE_NAMES = {"opening balances", "opening balance"}
PLACEHOLDER = UUID(int=1)  # stands in for account ids while validating transactions
Key = tuple[str, ...]


class ImportRejected(ValueError):
    def __init__(self, summary: ImportSummary):
        super().__init__("; ".join(summary.errors))
        self.summary = summary


@dataclass
class _Planned:
    date: date
    payee: str | None
    comment: str | None
    currency: str  # code of the commodity the transaction balances in
    # (account, side, amount, value in the currency; None when it is the amount)
    postings: list[tuple[Key, PostingSide, Decimal, Decimal | None]]


@dataclass
class _NewCommodity:
    code: str
    name: str
    kind: str
    decimals: int


@dataclass
class _Plan:
    summary: ImportSummary = field(default_factory=ImportSummary)
    new_accounts: list[tuple[Key, str | None, str]] = field(default_factory=list)  # key, note, commodity code
    new_commodities: list[_NewCommodity] = field(default_factory=list)
    prices: dict[tuple[str, str, date], Decimal] = field(default_factory=dict)
    transactions: list[_Planned] = field(default_factory=list)


def _places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


class _Commodities:
    """Turns the symbols and codes in a file into commodities: the catalog's, the user's own, or new ones."""

    def __init__(self, known: list[Commodity], default: Commodity, declared: list[CommodityDecl]):
        self.by_code = {c.code.casefold(): c for c in known}
        symbols: dict[str, list[Commodity]] = {}
        for commodity in known:
            if commodity.symbol:
                symbols.setdefault(commodity.symbol, []).append(commodity)
        self.by_symbol = {symbol: found[0] for symbol, found in symbols.items() if len(found) == 1}
        self.default = default
        self.declared = {d.symbol.casefold(): d for d in declared}
        self.new: dict[str, _NewCommodity] = {}
        self.codes: dict[str | None, str] = {}
        self.places: dict[str, int] = {}

    def resolve(self, token: str | None) -> str:
        """The code a symbol stands for; raises ValueError for one that cannot be a commodity."""
        if token in self.codes:
            return self.codes[token]
        if token is None:
            code = self.default.code
        elif token.casefold() in self.by_code:
            code = self.by_code[token.casefold()].code
        elif token in self.by_symbol:
            code = self.by_symbol[token].code
        elif CODE_PATTERN.match(token.upper()):
            code = token.upper()
            decl = self.declared.get(token.casefold())
            kind = decl.kind if decl and decl.kind in CommodityKind.ALL else CommodityKind.OTHER
            self.new[code] = _NewCommodity(code, (decl.name if decl and decl.name else code)[:80], kind, 0)
            self.by_code[code.casefold()] = Commodity(code=code, name=code, kind=kind, decimals=0)
        else:
            raise ValueError(f"'{token}' is not a commodity finode can use; use a code such as USD or INFY")
        self.codes[token] = code
        return code

    def decimals(self, code: str) -> int:
        if code in self.new:
            return self.new[code].decimals
        return self.by_code[code.casefold()].decimals

    def settle_new(self, observed: dict[str, int]) -> None:
        """New commodities get the decimals the file declares, else what it uses (at least two)."""
        for code, new in self.new.items():
            decl = self.declared.get(code.casefold())
            new.decimals = decl.decimals if decl and decl.decimals is not None else max(observed.get(code, 0), 2)


def _message(error: ValidationError) -> str:
    return "; ".join(item["msg"].removeprefix("Value error, ") for item in error.errors())


def _segment(name: str) -> str:
    """An account name as one ledger path segment."""
    return re.sub(r"\s+", " ", name.replace(":", "-")).strip()


def _resolve(path: str) -> Key:
    parts = [part.strip() for part in path.split(":")]
    if any(not part for part in parts):
        raise ValueError(f"'{path}' has an empty account name")
    root = ROOT_ALIASES.get(parts[0].casefold())
    if root is None:
        raise ValueError(
            f"'{path}' must start with Assets, Liabilities, Equity, Income or Expenses"
        )
    parts[0] = root
    if root == "Equity" and len(parts) == 2 and parts[1].casefold() in OPENING_BALANCE_NAMES:
        parts[1] = OPENING_BALANCES_ACCOUNT_NAME
    return tuple(parts)


def _formula_safe(text: str | None) -> str:
    text = text or ""
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


class DataService:
    def __init__(
        self, accounts: AccountService, ar: AccountRepository, tr: TransactionRepository, pr: ProfileRepository
    ):
        self.accounts = accounts
        self.ar = ar
        self.tr = tr
        self.pr = pr
        self.cr = accounts.cr

    # --- export -----------------------------------------------------------

    def _snapshot(self):
        accounts = self.accounts.ensure_roots()
        by_id = {a.aid: a for a in accounts}

        def path(aid: UUID) -> str:
            names = []
            current = by_id[aid]
            while True:
                names.append(_segment(current.name))
                if current.parent_id is None:
                    break
                current = by_id[current.parent_id]
            return ":".join(reversed(names))

        paths = {aid: path(aid) for aid in by_id}
        postings: dict[UUID, list] = {}
        for posting in sorted(self.tr.all_postings(), key=lambda p: (p.side != PostingSide.DEBIT, p.created)):
            postings.setdefault(posting.transaction, []).append(posting)
        transactions = sorted(self.tr.list(), key=lambda t: (t.date, t.created))
        return accounts, paths, postings, transactions

    def _is_multi(self, accounts, transactions) -> bool:
        """Whether anything other than the default currency is in play, so amounts need their commodity."""
        default = self.accounts.default_currency()
        return any(a.parent_id is not None and (a.commodity_id or default.cid) != default.cid for a in accounts) or any(
            t.currency_id != default.cid for t in transactions
        )

    def export_ledger(self) -> str:
        accounts, paths, postings, transactions = self._snapshot()
        catalog = self.accounts.catalog()
        default = self.accounts.default_currency()
        held = {a.aid: catalog[a.commodity_id or default.cid].code for a in accounts}
        labeled = self._is_multi(accounts, transactions)
        decls = [
            AccountDecl(paths[a.aid], a.details)
            for a in sorted(accounts, key=lambda a: paths[a.aid])
            if a.parent_id is not None
        ]
        entries = []
        for t in transactions:
            currency = catalog[t.currency_id].code
            lines = []
            for p in postings.get(t.tid, []):
                code = held[p.account]
                converted = code != currency
                lines.append(
                    LedgerPosting(
                        paths[p.account],
                        p.amount if p.side == PostingSide.DEBIT else -p.amount,
                        commodity=code,
                        cost=p.value if converted else None,
                        cost_commodity=currency if converted else None,
                    )
                )
            if len(lines) >= 2:
                entries.append(LedgerTransaction(t.date, t.payee or "", [t.comment] if t.comment else [], lines))
        if not labeled:
            return write(decls, entries, date.today())

        prices = [
            PriceDecl(p.date, p.commodity, p.price, p.quote)
            for p in sorted(self.accounts.prices.list(), key=lambda p: (p.date, p.commodity, p.quote))
            if not p.is_global
        ]
        used = set(held.values()) | {catalog[t.currency_id].code for t in transactions}
        used |= {p.symbol for p in prices} | {p.quote for p in prices if p.quote}
        declared = [
            CommodityDecl(
                c.code,
                c.decimals,
                c.name if c.user is not None else None,
                c.kind if c.user is not None else None,
            )
            for c in sorted(catalog.values(), key=lambda c: c.code)
            if c.code in used
        ]
        return write(decls, entries, date.today(), declared, prices, labeled=True)

    def export_csv(self) -> str:
        accounts, paths, postings, transactions = self._snapshot()
        catalog = self.accounts.catalog()
        default = self.accounts.default_currency()
        held = {a.aid: catalog[a.commodity_id or default.cid].code for a in accounts}
        multi = self._is_multi(accounts, transactions)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["date", "payee", "note", "account", "debit", "credit"] + (["commodity", "value", "currency"] if multi else []))
        for t in transactions:
            for p in postings.get(t.tid, []):
                shown = _plain(p.amount) if multi else f"{p.amount:.2f}"
                debit = shown if p.side == PostingSide.DEBIT else ""
                credit = shown if p.side == PostingSide.CREDIT else ""
                row = [
                    t.date.isoformat(), _formula_safe(t.payee), _formula_safe(t.comment),
                    paths[p.account], debit, credit,
                ]
                if multi:
                    row += [held[p.account], _plain(p.value), catalog[t.currency_id].code]
                writer.writerow(row)
        return out.getvalue()

    # --- import -----------------------------------------------------------

    def can_import(self) -> bool:
        return not self.tr.list(limit=1)

    def _existing_keys(self) -> dict[Key, UUID]:
        accounts = self.accounts.ensure_roots()
        by_id = {a.aid: a for a in accounts}
        keys: dict[Key, UUID] = {}
        for account in accounts:
            names = []
            current = account
            while True:
                names.append(current.name)
                if current.parent_id is None:
                    break
                current = by_id[current.parent_id]
            keys[tuple(reversed(names))] = account.aid
        return keys

    def _plan(self, text: str) -> _Plan:
        plan = _Plan()
        errors = plan.summary.errors
        if not self.can_import():
            errors.append(
                "Import only works while you have no transactions. Export your data first "
                "if you want to start over."
            )
            return plan

        journal = parse(text)
        errors.extend(journal.errors)
        existing = self._existing_keys()
        default = self.accounts.default_currency()
        commodities = _Commodities(list(self.accounts.catalog().values()), default, journal.commodities)
        catalog = self.accounts.catalog()
        by_aid = {a.aid: a for a in self.accounts.ensure_roots()}
        existing_commodity = {
            key: catalog[by_aid[aid].commodity_id].code if by_aid[aid].commodity_id else default.code
            for key, aid in existing.items()
        }

        def resolve(token: str | None, line: int) -> str | None:
            try:
                return commodities.resolve(token)
            except ValueError as e:
                errors.append(f"line {line}: {e}")
                return None

        for decl in journal.commodities:
            resolve(decl.symbol, decl.line)

        # Accounts: everything declared or posted to, plus their parents.
        declared: dict[Key, tuple[str | None, int]] = {}
        used: dict[Key, int] = {}
        held: dict[Key, dict[str, int]] = {}  # account -> commodity -> first line
        observed: dict[str, int] = {}
        for decl in journal.accounts:
            try:
                declared.setdefault(_resolve(decl.name), (decl.note, decl.line))
            except ValueError as e:
                errors.append(f"line {decl.line}: {e}")
        for transaction in journal.transactions:
            for posting in transaction.postings:
                if posting.amount == 0:
                    continue
                try:
                    key = _resolve(posting.account)
                except ValueError as e:
                    errors.append(f"line {posting.line}: {e}")
                    continue
                used.setdefault(key, posting.line)
                code = resolve(posting.commodity, posting.line)
                if code is not None:
                    held.setdefault(key, {}).setdefault(code, posting.line)
                    observed[code] = max(observed.get(code, 0), _places(posting.amount))
                if posting.cost is not None:
                    cost_code = resolve(posting.cost_commodity, posting.line)
                    if cost_code is not None:
                        observed[cost_code] = max(observed.get(cost_code, 0), _places(posting.cost))
        commodities.settle_new(observed)

        known: set[Key] = set(existing) | set(declared) | set(used)
        for key in list(known):
            for depth in range(2, len(key)):
                known.add(key[:depth])
        parents = {key[:-1] for key in known if len(key) > 1}

        for key, line in used.items():
            label = ":".join(key)
            if len(key) == 1:
                errors.append(f"line {line}: cannot post to the top-level account '{label}'")
            elif key in parents and not (key[0] in GROUP_POSTING_ROOT_NAMES and key[1:] != (OPENING_BALANCES_ACCOUNT_NAME,)):
                errors.append(
                    f"line {line}: '{label}' has sub-accounts, so it cannot be posted to; "
                    f"move those postings to a sub-account such as '{label}:Other'"
                )

        # What each account holds: one commodity, from its postings.
        planned_commodity: dict[Key, str] = {}
        for key, found in held.items():
            first_line = min(found.values())
            if len(found) > 1:
                names = " and ".join(sorted(found))
                if key[1:] == (OPENING_BALANCES_ACCOUNT_NAME,):
                    errors.append(
                        f"line {first_line}: '{':'.join(key)}' mixes {names}, but it can hold only one commodity: "
                        "write other commodities' opening balances as conversions, like '100 USD @@ 8300 INR'"
                    )
                else:
                    errors.append(
                        f"line {first_line}: '{':'.join(key)}' mixes {names}, but an account holds one commodity: "
                        f"split it into sub-accounts such as '{':'.join(key)}:{sorted(found)[0]}'"
                    )
                continue
            (code,) = found
            if key in existing_commodity and len(key) > 1 and existing_commodity[key] != code:
                errors.append(
                    f"line {first_line}: '{':'.join(key)}' holds {existing_commodity[key]} but the file posts {code} to it"
                )
                continue
            planned_commodity[key] = code

        new = sorted((key for key in known if key not in existing), key=lambda k: (len(k), k))
        limits = depth_limits(self.pr.read())
        for key in new:
            depth, limit = len(key) - 1, limits[key[0]]
            if depth > limit:
                line = declared.get(key, (None, used.get(key, 0)))[1] or next(
                    (n for k, n in used.items() if k[: len(key)] == key), 0
                )
                errors.append(
                    f"line {line}: '{':'.join(key)}' is {depth} levels deep, but {key[0]} allows "
                    f"{limit}. Raise the limit under Profile › Account depth, or flatten the account."
                )
            note = declared.get(key, (None, 0))[0]
            try:
                AccountCreate(name=key[-1], details=note, parent_id=PLACEHOLDER)
            except ValidationError as e:
                line = declared.get(key, (None, used.get(key, 0)))[1]
                errors.append(f"line {line}: account '{':'.join(key)}': {_message(e)}")
            # Without postings of its own an account holds what its parent holds.
            inherited = planned_commodity.get(key[:-1]) or existing_commodity.get(key[:-1]) or default.code
            planned_commodity.setdefault(key, inherited)
            plan.new_accounts.append((key, note, planned_commodity[key]))

        totals = {"Assets": Decimal("0.00"), "Liabilities": Decimal("0.00")}
        for transaction in journal.transactions:
            lines = [p for p in transaction.postings if p.amount != 0]
            if not lines:
                plan.summary.skipped_empty += 1
                continue
            payee = transaction.payee or None
            notes = list(transaction.notes)
            if payee and len(payee) > 40:
                notes.insert(0, payee)
                payee = payee[:40].rstrip()
            comment = " · ".join(notes) or None
            planned = self._plan_transaction(transaction, lines, payee, comment, commodities, errors)
            if planned is None:
                continue
            for key, side, amount, value in planned.postings:
                if key[0] in totals and planned_commodity.get(key) == default.code:
                    sign = 1 if (side == PostingSide.DEBIT) == (key[0] == "Assets") else -1
                    totals[key[0]] += sign * amount
            plan.transactions.append(planned)

        for price in journal.prices:
            base, quote = resolve(price.symbol, price.line), resolve(price.quote, price.line)
            if base is None or quote is None:
                continue
            if base == quote:
                errors.append(f"line {price.line}: a commodity cannot be priced in itself")
                continue
            plan.prices[(base, quote, price.date)] = price.price

        plan.new_commodities = list(commodities.new.values())
        summary = plan.summary
        summary.new_accounts = [":".join(key) for key, _, _ in plan.new_accounts]
        summary.accounts_reused = sum(1 for key in known if key in existing and len(key) > 1)
        summary.transactions = len(plan.transactions)
        summary.new_commodities = [c.code for c in plan.new_commodities]
        summary.other_commodities = sorted(
            {code for key, code in planned_commodity.items() if code != default.code and len(key) > 1}
        )
        summary.prices = len(plan.prices)
        if plan.transactions:
            summary.date_from = min(t.date for t in plan.transactions)
            summary.date_to = max(t.date for t in plan.transactions)
        summary.assets = totals["Assets"]
        summary.liabilities = totals["Liabilities"]
        if not plan.transactions and not errors:
            errors.append("The file has no transactions to import.")
        if len(errors) > MAX_REPORTED_ERRORS:
            extra = len(errors) - MAX_REPORTED_ERRORS
            del errors[MAX_REPORTED_ERRORS:]
            errors.append(f"…and {extra} more problems")
        return plan

    def _plan_transaction(
        self,
        transaction: LedgerTransaction,
        lines: list[LedgerPosting],
        payee: str | None,
        comment: str | None,
        commodities: _Commodities,
        errors: list[str],
    ) -> _Planned | None:
        """One transaction: its currency, and what each posting is worth in it."""
        try:
            keys = [_resolve(p.account) for p in lines]
            held = [commodities.resolve(p.commodity) for p in lines]
            costs = [commodities.resolve(p.cost_commodity) if p.cost is not None else None for p in lines]
        except ValueError:
            return None  # already reported while collecting accounts and commodities

        priced = {c for c in costs if c is not None}
        if len(priced) > 1:
            errors.append(
                f"line {transaction.line}: conversions in one transaction must all be priced in the same "
                f"commodity (found {' and '.join(sorted(priced))})"
            )
            return None
        currency = next(iter(priced)) if priced else held[0]
        if not priced and len(set(held)) > 1:
            errors.append(f"line {transaction.line}: mixes {' and '.join(sorted(set(held)))} without a price")
            return None

        postings = []
        for posting, key, code, cost in zip(lines, keys, held, costs):
            amount = abs(posting.amount)
            side = PostingSide.DEBIT if posting.amount > 0 else PostingSide.CREDIT
            if _places(amount) > commodities.decimals(code):
                errors.append(
                    f"line {posting.line}: '{_plain(amount)}' has more than {commodities.decimals(code)} "
                    f"decimal place{'' if commodities.decimals(code) == 1 else 's'}, which is what {code} allows"
                )
                return None
            value = None
            if code != currency:
                if posting.cost is None:
                    errors.append(
                        f"line {posting.line}: '{posting.account}' is in {code} but the transaction is in {currency}: "
                        f"say what it is worth, like '{_plain(amount)} {code} @@ <total> {currency}'"
                    )
                    return None
                value = posting.cost
            shown = value if value is not None else amount
            if _places(shown) > commodities.decimals(currency):
                errors.append(
                    f"line {posting.line}: '{_plain(shown)}' has more than {commodities.decimals(currency)} "
                    f"decimal place{'' if commodities.decimals(currency) == 1 else 's'}, which is what {currency} allows; "
                    "write the total with '@@'"
                )
                return None
            postings.append((key, side, amount, value))

        debits = sum((v if v is not None else a for _, s, a, v in postings if s == PostingSide.DEBIT), Decimal(0))
        credits = sum((v if v is not None else a for _, s, a, v in postings if s == PostingSide.CREDIT), Decimal(0))
        if debits != credits:
            errors.append(f"line {transaction.line}: does not balance in {currency} (off by {_plain(abs(debits - credits))})")
            return None
        try:
            TransactionCreate(
                date=transaction.date,
                payee=payee,
                comment=comment,
                postings=[
                    PostingCreate(account=PLACEHOLDER, side=s, amount=a, value=v) for _, s, a, v in postings
                ],
            )
        except ValidationError as e:
            errors.append(f"line {transaction.line}: {_message(e)}")
            return None
        return _Planned(transaction.date, payee, comment, currency, postings)

    def preview_import(self, text: str) -> ImportSummary:
        return self._plan(text).summary

    def run_import(self, text: str) -> ImportSummary:
        plan = self._plan(text)
        if plan.summary.errors:
            raise ImportRejected(plan.summary)
        ids = self._existing_keys()
        try:
            for new in plan.new_commodities:
                self.cr.create(code=new.code, name=new.name, kind=new.kind, decimals=new.decimals)
            self.cr.db.flush()
            self.accounts.reset_defaults()
            by_code = {c.code: c.cid for c in self.cr.list()}
            for key, note, code in plan.new_accounts:
                created = self.ar.create(
                    AccountCreate(name=key[-1], details=note, parent_id=ids[key[:-1]]), commodity_id=by_code[code]
                )
                ids[key] = created.aid
            for planned in plan.transactions:
                self.tr.create(
                    TransactionCreate(
                        date=planned.date,
                        payee=planned.payee,
                        comment=planned.comment,
                        postings=[
                            PostingCreate(account=ids[k], side=s, amount=a, value=v)
                            for k, s, a, v in planned.postings
                        ],
                    ),
                    by_code[planned.currency],
                    [v if v is not None else a for _, _, a, v in planned.postings],
                )
            for (base, quote, on), price in plan.prices.items():
                self.accounts.prices.pr.upsert(by_code[base], by_code[quote], on, price)
            self.tr.db.commit()
        except Exception:
            self.tr.db.rollback()
            raise
        finally:
            self.accounts.reset_defaults()
            self.accounts.prices.invalidate()
        return plan.summary
