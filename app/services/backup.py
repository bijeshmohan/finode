"""A complete backup of what a user has recorded, and restoring it into an empty ledger.

The ledger and CSV exports carry accounts and transactions; this one also carries everything
around them (settings, budget plan and goals, recurring rules, account flags such as
"part of the budget" and "closed"), so it can rebuild the whole book. Left out on purpose: access tokens and
connected apps (secrets and sign-ins to set up again) and the audit history (it describes the old rows).
Restoring creates everything with new ids, all or nothing in one database transaction.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import ValidationError

from ..config import settings
from ..currencies import find as find_currency
from ..limits import LimitReached, ensure_room
from ..models.category import BudgetCategory
from ..models.recurring import RecurringTransaction
from ..models.transaction import PostingSide
from ..repositories import AccountRepository, CategoryRepository, ProfileRepository, TransactionRepository
from ..repositories.budget import BudgetRepository
from ..repositories.recurring import RecurringRepository
from ..schemas.account import AccountCreate
from ..schemas.backup import (
    FORMAT,
    READS,
    VERSION,
    BackupAccount,
    BackupAllocation,
    BackupCategory,
    BackupFile,
    BackupGoal,
    BackupGoalMonth,
    BackupPosting,
    BackupProfile,
    BackupRecurring,
    BackupRecurringPosting,
    BackupTransaction,
    RestoreSummary,
)
from ..schemas.transaction import PostingCreate, TransactionCreate
from ..tags import clean_names, split_note
from .account import MAX_ACCOUNT_DEPTH, OPENING_BALANCES_ACCOUNT_NAME, AccountService

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
        self.cr = CategoryRepository(tr.db, tr.uid)

    # ---- backing up ------------------------------------------------------------------------------

    def export(self) -> dict:
        profile = self.pr.get_or_create()
        accounts = self.accounts.ensure_roots()
        postings: dict[UUID, list] = {}
        for p in sorted(self.tr.all_postings(), key=lambda p: (p.side != PostingSide.DEBIT, p.created)):
            postings.setdefault(p.transaction, []).append(p)
        recurring_rows = self.rr.postings()
        tags = self.tr.all_tag_map()
        file = BackupFile(
            format=FORMAT,
            version=VERSION,
            exported_at=datetime.now(UTC),
            profile=BackupProfile(
                first_name=profile.first_name,
                last_name=profile.last_name,
                default_currency=profile.currency,
            ),
            accounts=[
                BackupAccount(
                    id=a.aid,
                    parent_id=a.parent_id,
                    name=a.name,
                    details=a.details,
                    on_budget=a.on_budget,
                    closed_on=a.closed_on,
                    payment_category_id=a.payment_category_id,
                    system_key=a.system_key,
                )
                for a in accounts
            ],
            categories=[
                BackupCategory(
                    id=c.bcid,
                    name=c.name,
                    kind=c.kind,
                    parent_id=c.parent_id,
                    details=c.details,
                    closed_on=c.closed_on,
                    system_key=c.system_key,
                )
                for c in sorted(self.cr.list(), key=lambda c: (c.parent_id is not None, c.kind, c.name.lower()))
            ],
            transactions=[
                BackupTransaction(
                    id=t.tid,
                    date=t.date,
                    payee=t.payee,
                    comment=t.comment,
                    created_via=t.created_via,
                    updated_via=t.updated_via,
                    recurring_id=t.recurring_id,
                    recurring_date=t.recurring_date,
                    related_id=t.related_id,
                    tags=tags.get(t.tid, []),
                    source=t.source,
                    external_id=t.external_id,
                    source_url=t.source_url,
                    postings=[
                        BackupPosting(account=p.account, side=p.side, amount=p.amount, category=p.category_id)
                        for p in postings.get(t.tid, [])
                    ],
                )
                for t in sorted(self.tr.list(), key=lambda t: (t.date, t.created))
            ],
            recurring=[
                BackupRecurring(
                    id=r.rid,
                    from_account=r.from_account,
                    to_account=r.to_account,
                    amount=r.amount,
                    category=r.category_id,
                    postings=[
                        BackupRecurringPosting(
                            account=p.account, side=PostingSide(p.side), amount=p.amount, category=p.category_id
                        )
                        for p in recurring_rows.get(r.rid, [])
                    ],
                    payee=r.payee,
                    comment=r.comment,
                    tags=list(r.tags or []),
                    frequency=r.frequency,
                    every=r.every,
                    start_date=r.start_date,
                    end_date=r.end_date,
                    next_date=r.next_date,
                    last_date=r.last_date,
                    skipped_date=r.skipped_date,
                    active=r.active,
                    last_error=r.last_error,
                )
                for r in self.rr.list()
            ],
            allocations=[
                BackupAllocation(month=row.month, category_id=row.category_id, amount=row.amount)
                for row in self.br.list()
            ],
            goals=[
                BackupGoal(
                    name=g.name,
                    amount=g.amount,
                    target_date=g.target_date,
                    allocations=[
                        BackupGoalMonth(month=r.month, amount=r.amount)
                        for r in sorted(self.br.goal_allocations(), key=lambda r: r.month)
                        if r.goal_id == g.gid
                    ],
                )
                for g in sorted(self.br.goals(), key=lambda g: (g.target_date, g.name))
            ],
        )
        return file.model_dump(mode="json")

    # ---- restoring -------------------------------------------------------------------------------

    def can_restore(self) -> bool:
        """Only an empty ledger can be restored into: nothing recorded, no accounts of the user's own."""
        accounts = self.accounts.ensure_roots()
        own = [
            a
            for a in accounts
            if a.parent_id is not None and a.system_key is None and not self.accounts.is_opening_balances(a, accounts)
        ]
        return (
            not own
            and not self.cr.list()
            and not self.tr.account_ids_with_postings()
            and not self.rr.list()
            and not self.br.list()
            and not self.br.goals()
        )

    def restore(self, raw: dict, dry_run: bool = False) -> RestoreSummary:
        summary = RestoreSummary()
        try:
            file = BackupFile.model_validate(raw)
        except ValidationError as e:
            summary.errors = [f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in e.errors()[:8]]
            return summary
        if file.format != FORMAT:
            summary.errors = ["this is not a finode backup file."]
            return summary
        if file.version not in READS:
            summary.errors = [
                f"this backup is version {file.version}; this finode reads versions {', '.join(map(str, READS))}."
            ]
            return summary
        if not self.can_restore():
            summary.errors = [
                "a backup can only be restored into an empty ledger: you already have accounts, transactions, "
                "recurring transactions or a budget."
            ]
            return summary
        if file.version < 3:  # tags used to be #words in the note: they become tags, as in the migration
            for t in file.transactions:
                if not t.tags:
                    t.comment, t.tags = split_note(t.comment)
        self._upgrade(file)
        self._check(file, summary)
        for room in (
            lambda: ensure_room(len(file.accounts), settings.max_accounts, "accounts"),
            lambda: ensure_room(len(file.categories), settings.max_categories, "categories"),
            lambda: ensure_room(len(file.transactions), settings.max_transactions, "transactions"),
            lambda: ensure_room(len({n for t in file.transactions for n in t.tags}), settings.max_tags, "tags"),
        ):
            try:
                room()
            except LimitReached as e:
                summary.errors.append(f"this backup is bigger than your limits allow: {e}")
        summary.accounts = sum(1 for a in file.accounts if a.parent_id is not None)
        summary.categories = len(file.categories)
        summary.transactions = len(file.transactions)
        summary.recurring = len(file.recurring)
        summary.allocations = len(self._spending_plan(file))
        summary.goals = len(file.goals)
        summary.tags = len({n for t in file.transactions for n in t.tags})
        if file.transactions:
            summary.date_from = min(t.date for t in file.transactions)
            summary.date_to = max(t.date for t in file.transactions)
        if summary.errors or dry_run:
            return summary
        self._apply(file)
        return summary

    @staticmethod
    def _upgrade(file: BackupFile) -> None:
        """A file from before version 5 kept categories as Income and Expenses accounts (with the same ids). Make them
        categories: the accounts go, a line on one posts to Expenses or Income with the category on it, and the
        rules and plan rows (which already named the category by that id) follow."""
        if file.version >= 5:
            return
        by_id = {a.id: a for a in file.accounts}

        def root_of(account: BackupAccount) -> BackupAccount | None:
            seen: set[UUID] = set()
            while account.parent_id is not None and account.id not in seen and account.parent_id in by_id:
                seen.add(account.id)
                account = by_id[account.parent_id]
            return account if account.parent_id is None else None

        roots = {a.name: a.id for a in file.accounts if a.parent_id is None}
        books: dict[UUID, tuple[BackupAccount, str]] = {}
        for a in file.accounts:
            top = root_of(a)
            if a.parent_id is not None and top is not None and top.name in ("Expenses", "Income"):
                books[a.id] = (a, top.name)
        file.categories = [
            BackupCategory(
                id=a.id,
                name=a.name,
                kind="spending" if top == "Expenses" else "earning",
                parent_id=a.parent_id if a.parent_id in books else None,
                details=a.details,
                closed_on=a.closed_on,
                system_key=a.category_key,
            )
            for a, top in books.values()
        ]
        file.accounts = [a for a in file.accounts if a.id not in books]

        def place(account: UUID | None, category: UUID | None) -> tuple[UUID | None, UUID | None]:
            if account in books:
                return roots[books[account][1]], category or account
            return account, category

        for t in file.transactions:
            for p in t.postings:
                placed = place(p.account, p.category)
                p.account, p.category = cast(UUID, placed[0]), placed[1]
        for r in file.recurring:
            r.from_account, from_category = place(r.from_account, None)
            r.to_account, to_category = place(r.to_account, None)
            if from_category or to_category:
                r.category = r.category or to_category or from_category
            for p in r.postings:
                placed = place(p.account, p.category)
                p.account, p.category = cast(UUID, placed[0]), placed[1]

    def _check(self, file: BackupFile, summary: RestoreSummary) -> None:
        errors = summary.errors
        currency = find_currency(file.profile.default_currency)
        if currency is None:
            errors.append(f"the currency {file.profile.default_currency} is not one finode knows.")
            return
        if file.commodities or file.prices:
            errors.append(
                "this backup has assets or prices of its own, which finode no longer keeps: it keeps everything in one currency."
            )
        for number, t in enumerate(file.transactions, start=1):
            try:
                t.tags = clean_names(t.tags)
            except ValueError as e:
                errors.append(f"transaction {number}: {e}")
                break
        other = lambda code: code is not None and code.upper() != currency.code  # noqa: E731

        accounts = {a.id: a for a in file.accounts}
        if len(accounts) != len(file.accounts):
            errors.append("an account id appears twice.")
        for a in file.accounts:
            if a.parent_id is None and a.name not in ROOTS:
                errors.append(f"top-level account '{a.name}' is not one of {', '.join(ROOTS)}.")
            if a.parent_id is not None and a.parent_id not in accounts:
                errors.append(f"account '{a.name}' has a parent that is not in the file.")
            if other(a.commodity):
                errors.append(
                    f"account '{a.name}' holds {a.commodity}, but finode keeps one currency ({currency.code})."
                )
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
        too_deep = [a.name for a in file.accounts if (self._depth(a, accounts) or 0) > MAX_ACCOUNT_DEPTH]
        if too_deep:
            errors.append(
                f"accounts can be at most {MAX_ACCOUNT_DEPTH} levels deep (a category and a subcategory), "
                f"but {', '.join(too_deep[:3])}{' and more' if len(too_deep) > 3 else ''} go deeper: flatten them first."
            )
            return
        category_ids = {c.id for c in file.categories}
        for a in file.accounts:
            if a.payment_category_id is not None and a.payment_category_id not in category_ids:
                errors.append(f"account '{a.name}' points to a missing payment category.")
        for a in file.accounts:
            if a.parent_id is not None and accounts[a.parent_id].name in ("Expenses", "Income"):
                errors.append(f"'{a.name}' is an account under {accounts[a.parent_id].name}: those hold categories.")
                return
        postable = {a.id for a in file.accounts if a.parent_id is not None}
        postable |= {a.id for a in file.accounts if a.parent_id is None and a.name in ("Expenses", "Income")}
        self._check_categories(file, accounts, errors)
        rules = {r.id for r in file.recurring}
        references: set[tuple[str, str]] = set()
        for t in file.transactions:
            label = f"the transaction of {t.date} ({t.payee or 'no payee'})"
            if t.external_id and t.external_id.strip():
                key = ((t.source or "").strip().lower(), t.external_id.strip())
                if not key[0]:
                    errors.append(f"{label} has a reference but no source.")
                elif key in references:
                    errors.append(f"{label} uses the reference '{key[1]}' of source '{key[0]}' that another entry has.")
                references.add(key)
            if other(t.currency):
                errors.append(f"{label} is in {t.currency}, but finode keeps one currency ({currency.code}).")
            if len(t.postings) < 2:
                errors.append(f"{label} has fewer than two postings.")
            if any(p.account not in postable for p in t.postings):
                errors.append(f"{label} uses an account that is not in the file.")
            if any(p.amount <= 0 for p in t.postings):
                errors.append(f"{label} has a posting that is not positive.")
            if any(p.value is not None and p.value != p.amount for p in t.postings):
                errors.append(f"{label} converts between currencies, but finode keeps one currency ({currency.code}).")
            debit = sum((p.amount for p in t.postings if p.side == PostingSide.DEBIT), Decimal(0))
            credit = sum((p.amount for p in t.postings if p.side == PostingSide.CREDIT), Decimal(0))
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
            if (
                r.received_amount is not None
                or other(r.currency)
                or any(p.value is not None and p.value != p.amount for p in r.postings)
            ):
                errors.append(f"a recurring transaction ({r.payee or r.id}) converts between currencies.")
            if not r.postings and None in (r.from_account, r.to_account, r.amount):
                errors.append(
                    f"a recurring transaction ({r.payee or r.id}) has neither from, to and amount nor postings."
                )
        names = [" ".join(g.name.split()).lower() for g in file.goals]
        if len(set(names)) != len(names) or "" in names:
            errors.append("a goal has no name, or two goals have the same name.")
        for g in file.goals:
            if g.amount <= 0 or len(g.name) > 80:
                errors.append(f"the goal '{g.name}' has an amount that is not positive, or a name that is too long.")
                break
            saved = Decimal(0)
            for alloc in sorted(g.allocations, key=lambda x: x.month):
                saved += alloc.amount
                if saved < 0:
                    errors.append(f"the goal '{g.name}' would hold less than nothing in {alloc.month:%B %Y}.")
                    break
        for row in file.allocations:
            if row.category_id not in category_ids:
                errors.append("a budget entry refers to a category that is not in the file.")
                break

    @staticmethod
    def _check_categories(file: BackupFile, accounts: dict[UUID, BackupAccount], errors: list[str]) -> None:
        """The categories are sound (two levels, one kind in a group, names unique in a place) and a category on a line
        (or a rule) is one of the file's and fits the line: spending on Expenses or a payment out of the budget, earning
        on Income, nothing on Equity."""
        cats = {c.id: c for c in file.categories}
        if len(cats) != len(file.categories):
            errors.append("a category id appears twice.")
            return
        names: set[tuple[str, UUID | None, str]] = set()
        for c in file.categories:
            parent = cats.get(c.parent_id) if c.parent_id else None
            if c.kind not in ("spending", "earning"):
                errors.append(f"category '{c.name}' is neither spending nor earning.")
            elif c.parent_id is not None and (parent is None or parent.parent_id is not None or parent.kind != c.kind):
                errors.append(f"category '{c.name}' is in a group that is missing, too deep or of the other kind.")
            elif not c.name.strip() or len(c.name) > 40:
                errors.append("a category has no name, or a name that is too long.")
            elif (c.kind, c.parent_id, c.name.casefold()) in names:
                errors.append(f"category '{c.name}' appears twice in the same place.")
            names.add((c.kind, c.parent_id, c.name.casefold()))
            if errors:
                return

        def root(account: BackupAccount) -> str | None:
            seen: set[UUID] = set()
            while account.parent_id is not None and account.id not in seen:
                seen.add(account.id)
                account = accounts[account.parent_id]
            return account.name if account.parent_id is None else None

        lines: list[tuple[str, UUID | None, UUID | None]] = [
            (f"the transaction of {t.date}", p.account, p.category) for t in file.transactions for p in t.postings
        ]
        for r in file.recurring:
            lines += [(f"a recurring transaction ({r.payee or r.id})", p.account, p.category) for p in r.postings]
            if r.category is not None:
                lines.append((f"a recurring transaction ({r.payee or r.id})", None, r.category))
        for label, account, category in lines:
            if category is None:
                continue
            kind = cats[category].kind if category in cats else None
            where = root(accounts[account]) if account in accounts else None
            if kind is None:
                errors.append(f"{label} uses a category that is not in the file.")
            elif (where == "Expenses" and kind != "spending") or (where == "Income" and kind != "earning"):
                errors.append(f"{label} puts a {kind} category on a line to {where}.")
            elif where == "Equity":
                errors.append(f"{label} puts a category on a line to an equity account.")
            elif where in ("Assets", "Liabilities") and kind != "spending":
                errors.append(f"{label} puts an earning category on a line to a balance-sheet account.")
            if len(errors) > 20:
                return

    @staticmethod
    def _spending_plan(file: BackupFile) -> list:
        """The plan rows that belong to spending categories (a file from when the Plan had Build and Earn also carries
        rows for funds, loans and income accounts, which the budget no longer has: they are not categories)."""
        spending = {c.id for c in file.categories if c.kind == "spending"}
        return [r for r in file.allocations if r.category_id in spending]

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
            currency = find_currency(fields.default_currency)
            if currency is None:
                raise ValueError(f"unknown currency '{fields.default_currency}'!")
            profile.currency = currency.code
            db.add(profile)
            self.accounts.reset_defaults()

            roots = {a.name: a for a in self.accounts.ensure_roots() if a.parent_id is None}
            by_old = {a.id: a for a in file.accounts}
            ids: dict[UUID, UUID] = {}
            for a in file.accounts:
                if a.parent_id is None:
                    ids[a.id] = roots[a.name].aid
            # The built-in groups: the ones a file carries (by key) map onto the person's own. An empty built-in group whose
            # name the file uses for an account of its own (a plain "Cash" under Assets) steps aside for it.
            fixed = {a.system_key: a for a in self.accounts.ensure_roots() if a.system_key is not None}
            by_id_now = {a.aid: a for a in self.accounts.ensure_roots()}
            kept: set[UUID] = set()
            for a in file.accounts:
                if a.system_key in fixed:
                    ids[a.id] = fixed[a.system_key].aid
                    kept.add(a.id)
            taken = {
                (by_old[a.parent_id].name, a.name)
                for a in file.accounts
                if a.parent_id is not None and a.id not in kept and by_old[a.parent_id].parent_id is None
            }
            self.accounts.release_fixed_parents(
                [
                    f.aid
                    for f in fixed.values()
                    if (by_id_now[cast(UUID, f.parent_id)].name, f.name) in taken and f.aid not in ids.values()
                ]
            )
            opening = None
            for a in sorted(file.accounts, key=lambda a: self._depth(a, by_old) or 0):
                if a.parent_id is None or a.id in kept:
                    continue
                if (
                    a.name == OPENING_BALANCES_ACCOUNT_NAME
                    and by_old[a.parent_id].name == "Equity"
                    and by_old[a.parent_id].parent_id is None
                ):
                    opening = opening or self.accounts.opening_balances_account()
                    ids[a.id] = opening.aid
                    continue
                created = self.ar.create(
                    AccountCreate(name=a.name, details=a.details, parent_id=ids[a.parent_id]),
                    on_budget=a.on_budget,
                )
                ids[a.id] = created.aid
            for a in file.accounts:
                if a.parent_id is None or a.id in kept or ids[a.id] == (opening.aid if opening else None):
                    continue
                account = self.ar.read(ids[a.id])
                if account is None:
                    continue
                account.closed_on = a.closed_on
                db.add(account)
                db.flush()
            # Categories: a group first, then the categories in it.
            cats: dict[UUID, UUID] = {}
            for c in sorted(file.categories, key=lambda c: c.parent_id is not None):
                made_category = self.cr.add(
                    BudgetCategory(
                        user=self.cr.uid,
                        name=c.name,
                        details=c.details,
                        kind=c.kind,
                        parent_id=cats.get(c.parent_id) if c.parent_id else None,
                        system_key=c.system_key,
                        closed_on=c.closed_on,
                    )
                )
                cats[c.id] = made_category.bcid
            for a in file.accounts:
                if a.payment_category_id and a.id in ids and a.id not in kept:
                    account = self.ar.read(ids[a.id])
                    if account is not None:
                        account.payment_category_id = cats.get(a.payment_category_id)
                        db.add(account)
            db.flush()

            rules: dict[UUID, UUID] = {}
            for r in file.recurring:
                rule = RecurringTransaction(
                    user=self.rr.uid,
                    from_account=ids.get(r.from_account) if r.from_account else None,
                    to_account=ids.get(r.to_account) if r.to_account else None,
                    amount=r.amount,
                    category_id=cats.get(r.category) if r.category else None,
                    payee=r.payee,
                    comment=r.comment,
                    tags=clean_names(r.tags),
                    frequency=r.frequency,
                    every=r.every,
                    start_date=r.start_date,
                    end_date=r.end_date,
                    next_date=r.next_date,
                    last_date=r.last_date,
                    skipped_date=r.skipped_date,
                    active=r.active,
                    last_error=r.last_error,
                )
                self.rr.add(rule)
                self.rr.set_postings(
                    rule.rid,
                    [
                        {
                            "account": ids[p.account],
                            "side": p.side.value,
                            "amount": p.amount,
                            "category_id": cats.get(p.category) if p.category else None,
                        }
                        for p in r.postings
                    ],
                )
                rules[r.id] = rule.rid

            made: dict[UUID, UUID] = {}
            for t in file.transactions:
                postings = [
                    PostingCreate(
                        account=ids[p.account],
                        side=p.side,
                        amount=p.amount,
                        category=cats.get(p.category) if p.category else None,
                    )
                    for p in t.postings
                ]
                entry = self.tr.create(
                    TransactionCreate(
                        date=t.date,
                        payee=t.payee,
                        comment=t.comment,
                        postings=postings,
                        tags=t.tags,
                        source=t.source,
                        external_id=t.external_id,
                        source_url=t.source_url,
                    ),
                    origin=t.created_via,
                    recurring=(rules[t.recurring_id], t.recurring_date)
                    if t.recurring_id and t.recurring_date
                    else None,
                )
                made[t.id] = entry.tid
                if t.updated_via != t.created_via:
                    entry.updated_via = t.updated_via
                    db.add(entry)
            for t in file.transactions:  # links last: every entry has its new id by now
                if t.related_id in made:
                    linked = self.tr.read(made[t.id])
                    if linked is None:
                        continue
                    linked.related_id = made[t.related_id]
                    db.add(linked)
            for row in self._spending_plan(file):
                self.br.set(row.month, cats[row.category_id], row.amount)
            for g in file.goals:
                goal = self.br.add_goal(g.name, g.amount, g.target_date)
                for alloc in g.allocations:
                    self.br.set_goal(alloc.month, goal.gid, alloc.amount)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            self.accounts.reset_defaults()
