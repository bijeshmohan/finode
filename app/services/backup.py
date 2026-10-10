"""A complete backup of what a user has recorded, and restoring it into an empty ledger.

The ledger and CSV exports carry accounts, transactions and prices; this one also carries everything
around them (settings, own assets, budget plan and targets, recurring rules, account flags such as
"part of the budget" and "closed"), so it can rebuild the whole book. Left out on purpose: access tokens and
connected apps (secrets and sign-ins to set up again) and the audit history (it describes the old rows).
Restoring creates everything with new ids, all or nothing in one database transaction.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError

from ..models.commodity import CommodityKind
from ..models.recurring import RecurringTransaction
from ..models.transaction import PostingSide
from ..repositories import AccountRepository, ProfileRepository, TransactionRepository
from ..repositories.budget import BudgetRepository
from ..repositories.recurring import RecurringRepository
from ..schemas.account import AccountCreate
from ..schemas.backup import (
    FORMAT,
    VERSION,
    BackupAccount,
    BackupAllocation,
    BackupCommodity,
    BackupFile,
    BackupPosting,
    BackupPrice,
    BackupProfile,
    BackupRecurring,
    BackupRecurringPosting,
    BackupTarget,
    BackupTransaction,
    RestoreSummary,
)
from ..schemas.transaction import PostingCreate, TransactionCreate
from .account import OPENING_BALANCES_ACCOUNT_NAME, AccountService

ROOTS = ("Assets", "Liabilities", "Equity", "Income", "Expenses")


class BackupService:
    def __init__(
        self,
        accounts: AccountService,
        ar: AccountRepository,
        tr: TransactionRepository,
        pr: ProfileRepository,
        rr: RecurringRepository,
        br: BudgetRepository,
    ):
        self.accounts = accounts
        self.ar = ar
        self.tr = tr
        self.pr = pr
        self.rr = rr
        self.br = br
        self.cr = accounts.cr

    # ---- backing up ------------------------------------------------------------------------------

    def export(self) -> dict:
        catalog = self.accounts.catalog()
        code = lambda cid: catalog[cid].code if cid else None  # noqa: E731
        profile = self.pr.get_or_create()
        accounts = self.accounts.ensure_roots()
        postings: dict[UUID, list] = {}
        for p in sorted(self.tr.all_postings(), key=lambda p: (p.side != PostingSide.DEBIT, p.created)):
            postings.setdefault(p.transaction, []).append(p)
        recurring_rows = self.rr.postings()
        file = BackupFile(
            format=FORMAT,
            version=VERSION,
            exported_at=datetime.now(timezone.utc),
            profile=BackupProfile(
                first_name=profile.first_name,
                last_name=profile.last_name,
                default_currency=self.accounts.default_currency().code,
                max_depth_assets=profile.max_depth_assets,
                max_depth_liabilities=profile.max_depth_liabilities,
                max_depth_equity=profile.max_depth_equity,
                max_depth_income=profile.max_depth_income,
                max_depth_expenses=profile.max_depth_expenses,
            ),
            commodities=[
                BackupCommodity(code=c.code, name=c.name, kind=c.kind, decimals=c.decimals, symbol=c.symbol)
                for c in self.cr.list()
                if c.user is not None
            ],
            prices=[
                BackupPrice(commodity=code(p.commodity_id), quote=code(p.quote_id), date=p.date, price=p.price)
                for p in self.accounts.prices.pr.list()
            ],
            accounts=[
                BackupAccount(
                    id=a.aid, parent_id=a.parent_id, name=a.name, details=a.details, commodity=code(a.commodity_id),
                    on_budget=a.on_budget, closed_on=a.closed_on, payment_category_id=a.payment_category_id,
                )
                for a in accounts
            ],
            transactions=[
                BackupTransaction(
                    id=t.tid, date=t.date, payee=t.payee, comment=t.comment, currency=code(t.currency_id),
                    created_via=t.created_via, updated_via=t.updated_via,
                    recurring_id=t.recurring_id, recurring_date=t.recurring_date,
                    postings=[
                        BackupPosting(account=p.account, side=p.side, amount=p.amount, value=p.value)
                        for p in postings.get(t.tid, [])
                    ],
                )
                for t in sorted(self.tr.list(), key=lambda t: (t.date, t.created))
            ],
            recurring=[
                BackupRecurring(
                    id=r.rid, from_account=r.from_account, to_account=r.to_account, amount=r.amount,
                    received_amount=r.received_amount, currency=r.currency,
                    postings=[
                        BackupRecurringPosting(account=p.account, side=PostingSide(p.side), amount=p.amount, value=p.value)
                        for p in recurring_rows.get(r.rid, [])
                    ],
                    payee=r.payee, comment=r.comment, frequency=r.frequency, every=r.every,
                    start_date=r.start_date, end_date=r.end_date, next_date=r.next_date, last_date=r.last_date,
                    active=r.active, last_error=r.last_error,
                )
                for r in self.rr.list()
            ],
            allocations=[
                BackupAllocation(month=row.month, account_id=row.account_id, amount=row.amount)
                for row in self.br.list()
            ],
            targets=[
                BackupTarget(account_id=t.account_id, kind=t.kind, amount=t.amount, target_date=t.target_date)
                for t in self.br.targets().values()
            ],
        )
        return file.model_dump(mode="json")

    # ---- restoring -------------------------------------------------------------------------------

    def can_restore(self) -> bool:
        """Only an empty ledger can be restored into: nothing recorded, no accounts of the user's own."""
        accounts = self.accounts.ensure_roots()
        own = [
            a for a in accounts
            if a.parent_id is not None and not self.accounts.is_opening_balances(a, accounts)
        ]
        return not own and not self.tr.account_ids_with_postings() and not self.rr.list() and not self.br.list()

    def restore(self, raw: dict, dry_run: bool = False) -> RestoreSummary:
        summary = RestoreSummary()
        try:
            file = BackupFile.model_validate(raw)
        except ValidationError as e:
            summary.errors = [
                f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in e.errors()[:8]
            ]
            return summary
        if file.format != FORMAT:
            summary.errors = ["this is not a finode backup file."]
            return summary
        if file.version != VERSION:
            summary.errors = [f"this backup is version {file.version}; this finode reads version {VERSION}."]
            return summary
        if not self.can_restore():
            summary.errors = [
                "a backup can only be restored into an empty ledger: you already have accounts, transactions, "
                "recurring transactions or a budget."
            ]
            return summary
        self._check(file, summary)
        summary.accounts = sum(1 for a in file.accounts if a.parent_id is not None)
        summary.transactions = len(file.transactions)
        summary.recurring = len(file.recurring)
        summary.allocations = len(file.allocations)
        summary.targets = len(file.targets)
        summary.prices = len(file.prices)
        own = {c.code for c in self.cr.list() if c.user is not None}
        summary.commodities = [c.code for c in file.commodities if c.code not in own]
        if file.transactions:
            summary.date_from = min(t.date for t in file.transactions)
            summary.date_to = max(t.date for t in file.transactions)
        if summary.errors or dry_run:
            return summary
        self._apply(file)
        return summary

    def _check(self, file: BackupFile, summary: RestoreSummary) -> None:
        errors = summary.errors
        builtin = {c.code for c in self.cr.list() if c.user is None}
        own = {c.code: c for c in self.cr.list() if c.user is not None}
        for c in file.commodities:
            if c.code in builtin:
                errors.append(f"commodity {c.code} is a built-in currency.")
            if c.kind not in CommodityKind.ALL or c.kind == CommodityKind.CURRENCY:
                errors.append(f"commodity {c.code} has an unsupported kind '{c.kind}'.")
            if c.code in own and own[c.code].kind != c.kind:
                errors.append(f"commodity {c.code} already exists as a {own[c.code].kind}.")
        known = builtin | set(own) | {c.code for c in file.commodities}
        if file.profile.default_currency not in builtin:
            errors.append(f"the default currency {file.profile.default_currency} is not a built-in currency.")

        accounts = {a.id: a for a in file.accounts}
        if len(accounts) != len(file.accounts):
            errors.append("an account id appears twice.")
        for a in file.accounts:
            if a.parent_id is None and a.name not in ROOTS:
                errors.append(f"top-level account '{a.name}' is not one of {', '.join(ROOTS)}.")
            if a.parent_id is not None and a.parent_id not in accounts:
                errors.append(f"account '{a.name}' has a parent that is not in the file.")
            if a.parent_id is not None and a.commodity not in known:
                errors.append(f"account '{a.name}' holds an unknown commodity {a.commodity}.")
            if ":" in a.name:
                errors.append(f"account name '{a.name}' contains ':'.")
        if errors:
            return
        for a in file.accounts:  # a chain that never reaches a top-level account is a cycle
            seen, current = set(), a
            while current.parent_id is not None and current.id not in seen:
                seen.add(current.id)
                current = accounts[current.parent_id]
        if any(self._depth(a, accounts) is None for a in file.accounts):
            errors.append("the accounts contain a cycle.")
            return
        for a in file.accounts:
            for ref in (a.payment_category_id,):
                if ref is not None and ref not in accounts:
                    errors.append(f"account '{a.name}' points to a missing payment category.")
        postable = {a.id for a in file.accounts if a.parent_id is not None}
        rules = {r.id for r in file.recurring}
        for t in file.transactions:
            label = f"the transaction of {t.date} ({t.payee or 'no payee'})"
            if t.currency not in known:
                errors.append(f"{label} is in an unknown currency {t.currency}.")
            if len(t.postings) < 2:
                errors.append(f"{label} has fewer than two postings.")
            if any(p.account not in postable for p in t.postings):
                errors.append(f"{label} uses an account that is not in the file.")
            if any(p.amount <= 0 or p.value <= 0 for p in t.postings):
                errors.append(f"{label} has a posting that is not positive.")
            debit = sum((p.value for p in t.postings if p.side == PostingSide.DEBIT), Decimal(0))
            credit = sum((p.value for p in t.postings if p.side == PostingSide.CREDIT), Decimal(0))
            if debit != credit:
                errors.append(f"{label} does not balance (debits {debit:f}, credits {credit:f}).")
            if t.recurring_id is not None and t.recurring_id not in rules:
                errors.append(f"{label} points to a recurring rule that is not in the file.")
            if len(errors) > 20:
                break
        for r in file.recurring:
            used = [r.from_account, r.to_account, *(p.account for p in r.postings)]
            if any(a is not None and a not in postable for a in used):
                errors.append(f"a recurring transaction ({r.payee or r.id}) uses an account that is not in the file.")
            if not r.postings and None in (r.from_account, r.to_account, r.amount):
                errors.append(f"a recurring transaction ({r.payee or r.id}) has neither from, to and amount nor postings.")
        for row in [*file.allocations, *file.targets]:
            if row.account_id not in postable:
                errors.append("a budget entry refers to an account that is not in the file.")
                break
        for p in file.prices:
            if p.commodity not in known or p.quote not in known:
                errors.append(f"a price uses an unknown commodity ({p.commodity}/{p.quote}).")
                break

    @staticmethod
    def _depth(account: BackupAccount, accounts: dict[UUID, BackupAccount]) -> int | None:
        depth, current, seen = 0, account, set()
        while current.parent_id is not None:
            if current.id in seen:
                return None
            seen.add(current.id)
            current = accounts[current.parent_id]
            depth += 1
        return depth

    def _apply(self, file: BackupFile) -> None:
        db = self.tr.db
        try:
            profile = self.pr.get_or_create()
            fields = file.profile
            profile.first_name, profile.last_name = fields.first_name, fields.last_name
            for key in ("assets", "liabilities", "equity", "income", "expenses"):
                setattr(profile, f"max_depth_{key}", getattr(fields, f"max_depth_{key}"))
            existing = {c.code: c for c in self.cr.list() if c.user is not None}
            for c in file.commodities:
                if c.code not in existing:
                    self.cr.create(code=c.code, name=c.name, kind=c.kind, decimals=c.decimals, symbol=c.symbol)
            db.flush()
            self.accounts.reset_defaults()
            by_code = {c.code: c.cid for c in self.cr.list()}
            profile.default_commodity_id = by_code[fields.default_currency]
            db.add(profile)
            self.accounts.reset_defaults()

            roots = {a.name: a for a in self.accounts.ensure_roots() if a.parent_id is None}
            by_old = {a.id: a for a in file.accounts}
            ids: dict[UUID, UUID] = {}
            for a in file.accounts:
                if a.parent_id is None:
                    ids[a.id] = roots[a.name].aid
            opening = None
            for a in sorted(file.accounts, key=lambda a: self._depth(a, by_old)):
                if a.parent_id is None:
                    continue
                if a.name == OPENING_BALANCES_ACCOUNT_NAME and by_old[a.parent_id].name == "Equity" and by_old[a.parent_id].parent_id is None:
                    opening = opening or self.accounts.opening_balances_account()
                    ids[a.id] = opening.aid
                    continue
                created = self.ar.create(
                    AccountCreate(name=a.name, details=a.details, parent_id=ids[a.parent_id]),
                    commodity_id=by_code[a.commodity],
                    on_budget=a.on_budget,
                )
                ids[a.id] = created.aid
            for a in file.accounts:
                if a.parent_id is None or ids[a.id] == (opening.aid if opening else None):
                    continue
                account = self.ar.read(ids[a.id])
                account.closed_on = a.closed_on
                account.payment_category_id = ids.get(a.payment_category_id) if a.payment_category_id else None
                db.add(account)
            db.flush()

            rules: dict[UUID, UUID] = {}
            for r in file.recurring:
                rule = RecurringTransaction(
                    user=self.rr.uid,
                    from_account=ids.get(r.from_account) if r.from_account else None,
                    to_account=ids.get(r.to_account) if r.to_account else None,
                    amount=r.amount, received_amount=r.received_amount, currency=r.currency,
                    payee=r.payee, comment=r.comment, frequency=r.frequency, every=r.every,
                    start_date=r.start_date, end_date=r.end_date, next_date=r.next_date, last_date=r.last_date,
                    active=r.active, last_error=r.last_error,
                )
                self.rr.add(rule)
                self.rr.set_postings(
                    rule.rid,
                    [{"account": ids[p.account], "side": p.side.value, "amount": p.amount, "value": p.value} for p in r.postings],
                )
                rules[r.id] = rule.rid

            for t in file.transactions:
                postings = [
                    PostingCreate(account=ids[p.account], side=p.side, amount=p.amount, value=p.value)
                    for p in t.postings
                ]
                created = self.tr.create(
                    TransactionCreate(date=t.date, payee=t.payee, comment=t.comment, postings=postings),
                    by_code[t.currency],
                    [p.value for p in t.postings],
                    origin=t.created_via,
                    recurring=(rules[t.recurring_id], t.recurring_date) if t.recurring_id and t.recurring_date else None,
                )
                if t.updated_via != t.created_via:
                    created.updated_via = t.updated_via
                    db.add(created)
            for p in file.prices:
                self.accounts.prices.pr.upsert(by_code[p.commodity], by_code[p.quote], p.date, p.price)
            for row in file.allocations:
                self.br.set(row.month, ids[row.account_id], row.amount)
            for target in file.targets:
                self.br.set_target(ids[target.account_id], target.kind, target.amount, target.target_date)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            self.accounts.reset_defaults()
            self.accounts.prices.invalidate()
