"""Export to and import from the ledger journal format (and CSV for spreadsheets)."""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError

from ..clock import local_today
from ..config import settings
from ..ledger import AccountDecl, LedgerPosting, LedgerTransaction, parse, write
from ..ledger.parse import _plain
from ..limits import LimitReached, ensure_room
from ..models.transaction import PostingSide
from ..repositories import AccountRepository, ProfileRepository, TransactionRepository
from ..schemas.account import AccountCreate
from ..schemas.data import ImportSummary
from ..schemas.transaction import PostingCreate, TransactionCreate
from .account import GROUP_POSTING_ROOT_NAMES, MAX_ACCOUNT_DEPTH, OPENING_BALANCES_ACCOUNT_NAME, AccountService

MAX_REPORTED_ERRORS = 20
ROOT_ALIASES = {
    "assets": "Assets",
    "asset": "Assets",
    "liabilities": "Liabilities",
    "liability": "Liabilities",
    "equity": "Equity",
    "income": "Income",
    "revenue": "Income",
    "revenues": "Income",
    "expenses": "Expenses",
    "expense": "Expenses",
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
    date: Date
    payee: str | None
    comment: str | None
    postings: list[tuple[Key, PostingSide, Decimal]]  # account, side, amount


@dataclass
class _Plan:
    release: list[UUID] = field(default_factory=list)  # empty built-in groups the file does not use: they step aside
    summary: ImportSummary = field(default_factory=ImportSummary)
    new_accounts: list[tuple[Key, str | None]] = field(default_factory=list)  # key, note
    transactions: list[_Planned] = field(default_factory=list)


def _places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


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
        raise ValueError(f"'{path}' must start with Assets, Liabilities, Equity, Income or Expenses")
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

    def export_ledger(self) -> str:
        accounts, paths, postings, transactions = self._snapshot()
        decls = [
            AccountDecl(paths[a.aid], a.details)
            for a in sorted(accounts, key=lambda a: paths[a.aid])
            if a.parent_id is not None
        ]
        entries = []
        for t in transactions:
            lines = [
                LedgerPosting(paths[p.account], p.amount if p.side == PostingSide.DEBIT else -p.amount)
                for p in postings.get(t.tid, [])
            ]
            if len(lines) >= 2:
                entries.append(LedgerTransaction(t.date, t.payee or "", [t.comment] if t.comment else [], lines))
        return write(decls, entries, local_today())

    def export_csv(self) -> str:
        _accounts, paths, postings, transactions = self._snapshot()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["date", "payee", "note", "account", "debit", "credit"])
        for t in transactions:
            for p in postings.get(t.tid, []):
                shown = f"{p.amount:.2f}"
                debit = shown if p.side == PostingSide.DEBIT else ""
                credit = shown if p.side == PostingSide.CREDIT else ""
                writer.writerow(
                    [
                        t.date.isoformat(),
                        _formula_safe(t.payee),
                        _formula_safe(t.comment),
                        paths[p.account],
                        debit,
                        credit,
                    ]
                )
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
                "Import only works while you have no transactions. Export your data first if you want to start over."
            )
            return plan

        journal = parse(text)
        errors.extend(journal.errors)
        existing = self._existing_keys()
        currency = self.accounts.currency()
        by_aid = {a.aid: a for a in self.accounts.ensure_roots()}

        def label_ok(label: str | None) -> bool:
            """Amounts may be written bare, or with the code or sign of the person's own currency."""
            return label is None or label.casefold() in {currency.code.casefold(), (currency.symbol or "").casefold()}

        # Accounts: everything declared or posted to, plus their parents.
        declared: dict[Key, tuple[str | None, int]] = {}
        used: dict[Key, int] = {}
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
                if not label_ok(posting.commodity):
                    errors.append(
                        f"line {posting.line}: the amount is in '{posting.commodity}' but your currency is "
                        f"{currency.code}: finode keeps one currency (you can change it in Settings before importing)"
                    )

        # An empty built-in group the file wants as a plain account (a posting to "Assets:Cash") steps aside for it; the groups
        # it builds on ("Assets:Bank Accounts:HDFC") and the ones it does not mention stay.
        parents_wanted = {key[:depth] for key in (*declared, *used) for depth in range(2, len(key))}
        for account in self.accounts.empty_fixed_parents():
            key = next((k for k, aid in existing.items() if aid == account.aid), None)
            if key is not None and key in {*declared, *used} and key not in parents_wanted:
                existing.pop(key)
                plan.release.append(account.aid)

        known: set[Key] = set(existing) | set(declared) | set(used)
        for key in list(known):
            for depth in range(2, len(key)):
                known.add(key[:depth])
        parents = {key[:-1] for key in known if len(key) > 1}

        for key, line in used.items():
            label = ":".join(key)
            if len(key) == 1:
                errors.append(f"line {line}: cannot post to the top-level account '{label}'")
            elif key in parents and not (
                key[0] in GROUP_POSTING_ROOT_NAMES and key[1:] != (OPENING_BALANCES_ACCOUNT_NAME,)
            ):
                errors.append(
                    f"line {line}: '{label}' has sub-accounts, so it cannot be posted to; "
                    f"move those postings to a sub-account such as '{label}:Other'"
                )

        new = sorted((key for key in known if key not in existing), key=lambda k: (len(k), k))
        for key in new:
            depth = len(key) - 1
            if depth > MAX_ACCOUNT_DEPTH:
                line = declared.get(key, (None, used.get(key, 0)))[1] or next(
                    (n for k, n in used.items() if k[: len(key)] == key), 0
                )
                errors.append(
                    f"line {line}: '{':'.join(key)}' is {depth} levels deep, but accounts can be at most "
                    f"{MAX_ACCOUNT_DEPTH} levels deep (a category and a subcategory): flatten the account."
                )
            note = declared.get(key, (None, 0))[0]
            try:
                AccountCreate(name=key[-1], details=note, parent_id=PLACEHOLDER)
            except ValidationError as e:
                line = declared.get(key, (None, used.get(key, 0)))[1]
                errors.append(f"line {line}: account '{':'.join(key)}': {_message(e)}")
            plan.new_accounts.append((key, note))

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
            planned = self._plan_transaction(transaction, lines, payee, comment, currency.decimals, errors)
            if planned is None:
                continue
            for key, side, amount in planned.postings:
                if key[0] in totals:
                    sign = 1 if (side == PostingSide.DEBIT) == (key[0] == "Assets") else -1
                    totals[key[0]] += sign * amount
            plan.transactions.append(planned)

        summary = plan.summary
        summary.new_accounts = [":".join(key) for key, _ in plan.new_accounts]
        summary.accounts_reused = sum(1 for key in known if key in existing and len(key) > 1)
        summary.transactions = len(plan.transactions)
        if plan.transactions:
            summary.date_from = min(t.date for t in plan.transactions)
            summary.date_to = max(t.date for t in plan.transactions)
        summary.assets = totals["Assets"]
        summary.liabilities = totals["Liabilities"]
        if not plan.transactions and not errors:
            errors.append("The file has no transactions to import.")
        for room in (
            lambda: ensure_room(len(by_aid), settings.max_accounts, "accounts", len(plan.new_accounts)),
            lambda: ensure_room(self.tr.count(), settings.max_transactions, "transactions", len(plan.transactions)),
        ):
            try:
                room()
            except LimitReached as e:
                errors.append(f"This file is too big for your limits: {e}")
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
        decimals: int,
        errors: list[str],
    ) -> _Planned | None:
        """One transaction: its postings, checked the way entering it by hand would be."""
        try:
            keys = [_resolve(p.account) for p in lines]
        except ValueError:
            return None  # already reported while collecting accounts

        postings = []
        for posting, key in zip(lines, keys, strict=False):
            amount = abs(posting.amount)
            side = PostingSide.DEBIT if posting.amount > 0 else PostingSide.CREDIT
            if _places(amount) > decimals:
                errors.append(
                    f"line {posting.line}: '{_plain(amount)}' has more than {decimals} "
                    f"decimal place{'' if decimals == 1 else 's'}, which is what your currency allows"
                )
                return None
            postings.append((key, side, amount))

        debits = sum((a for _, s, a in postings if s == PostingSide.DEBIT), Decimal(0))
        credits = sum((a for _, s, a in postings if s == PostingSide.CREDIT), Decimal(0))
        if debits != credits:
            errors.append(f"line {transaction.line}: does not balance (off by {_plain(abs(debits - credits))})")
            return None
        try:
            TransactionCreate(
                date=transaction.date,
                payee=payee,
                comment=comment,
                postings=[PostingCreate(account=PLACEHOLDER, side=s, amount=a) for _, s, a in postings],
            )
        except ValidationError as e:
            errors.append(f"line {transaction.line}: {_message(e)}")
            return None
        return _Planned(transaction.date, payee, comment, postings)

    def preview_import(self, text: str) -> ImportSummary:
        return self._plan(text).summary

    def run_import(self, text: str) -> ImportSummary:
        plan = self._plan(text)
        if plan.summary.errors:
            raise ImportRejected(plan.summary)
        ids = self._existing_keys()
        try:
            self.accounts.release_fixed_parents(plan.release)
            ids = {k: v for k, v in ids.items() if v not in plan.release}
            for key, note in plan.new_accounts:
                created = self.ar.create(AccountCreate(name=key[-1], details=note, parent_id=ids[key[:-1]]))
                ids[key] = created.aid
            for planned in plan.transactions:
                self.tr.create(
                    TransactionCreate(
                        date=planned.date,
                        payee=planned.payee,
                        comment=planned.comment,
                        postings=[PostingCreate(account=ids[k], side=s, amount=a) for k, s, a in planned.postings],
                    ),
                    origin="import",
                )
            self.tr.db.commit()
        except Exception:
            self.tr.db.rollback()
            raise
        finally:
            self.accounts.reset_defaults()
        return plan.summary
