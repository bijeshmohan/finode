"""Converting a person's books to cash flow: every account they keep is one of the four types and part of the budget,
and investment and loan accounts become categories.

`plan` works out everything and changes nothing; `apply` carries a plan out in one go. Two callers use it: the command
a person's books are converted with once (`finode.commands.cash_flow`, strict: it refuses what it cannot decide) and
backup restore of a file made before the change (not strict: it decides by the rules below).

- Investments and Loans and every account under them are retired.
- A line on a retired account in an entry that also moves money in a kept account: money **into** the retired account
  posts to Expenses with its own spending category, else a category named after the account; money **out of** it
  posts to Income with its own earning category, else "Borrowed" (a loan) or "Redeemed" (an investment).
- An entry that touches no kept account and no person (an opening balance of a loan, a fund's value update) is deleted.
- Strict: an account outside the budget that is not retired, an entry between a retired account and a person with
  nothing in the budget, and an entry the rewrite would put on both sides of Expenses or Income are left to the person.
  Not strict: the account is kept and put in the budget, the entry with a person is rewritten as above, and the
  two-sided one posts its retired lines to Opening Balances instead (cash unchanged, nothing for the budget).
- Every kept account goes under its type by its root (Assets: Bank Account, Liabilities: Credit Card) unless it is
  under one already; the built-in groups take the types' names; a person's own groups and the retired ones go.
"""

import builtins
from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from ..models.account import Account
from ..models.category import BudgetCategory
from ..models.transaction import Posting, PostingSide
from ..repositories import TransactionRepository
from ..repositories.recurring import RecurringRepository
from ..repositories.shared_expense import SharedExpenseRepository
from ..schemas.account import AccountBase
from ..schemas.cash_flow import AccountMove, ConversionPlan, ConversionResult, EntryChange
from ..schemas.category import CategoryRead
from .account import AccountService
from .account_types import RETIRED_KEYS, TYPE_KEYS, TYPE_NAMES, TYPE_ROOTS
from .category import CategoryService

LOAN_INCOME = "Borrowed"
INVESTMENT_INCOME = "Redeemed"
NAME_LIMIT = 40

# A label for a rewritten line: a category that exists (its id) or one to make (its name in one form, and its kind).
CategoryRef = UUID | tuple[str, str]
# Where a rewritten line goes: the Expenses or Income root, or Opening Balances.
Target = str


class ConversionRefused(ValueError): ...


@dataclass
class _Work:
    roots: dict[str, UUID]
    type_groups: dict[str, UUID | None]  # each type's group, None for one to make
    renames: dict[UUID, str]  # a type's group that still has its old name
    places: list[tuple[UUID, str, str]] = field(default_factory=list)  # account, type key, name
    retargets: list[tuple[UUID, Target, CategoryRef | None]] = field(default_factory=list)
    deletes: list[UUID] = field(default_factory=list)
    rules: list[tuple[UUID, dict[UUID, tuple[Target, CategoryRef | None]]]] = field(default_factory=list)
    ends: list[UUID] = field(default_factory=list)
    accounts_to_delete: list[UUID] = field(default_factory=list)
    retired_accounts: list[UUID] = field(default_factory=list)  # the investment and loan accounts among them
    new_categories: dict[tuple[str, str], str] = field(default_factory=dict)  # (name in one form, kind) → name
    reopen: set[UUID] = field(default_factory=set)


class CashFlowConversion:
    def __init__(
        self, accounts: AccountService, tr: TransactionRepository, rr: RecurringRepository, categories: CategoryService
    ):
        self.accounts = accounts
        self.ar = accounts.ar
        self.tr = tr
        self.rr = rr
        self.categories = categories

    def plan(
        self,
        off_budget_ids: set[UUID],
        strict: bool,
        retire_ids: set[UUID] | None = None,
        types: dict[UUID, str] | None = None,
        group_ids: set[UUID] | None = None,
    ) -> ConversionPlan:
        """`retire_ids`: accounts or groups the person chose to retire as well (their worth goes, like an investment's;
        under Liabilities, like a loan's). `types`: an account's or a group's accounts' type, chosen by the person (an
        account outside the budget given a type goes into the budget). `group_ids`: accounts that were groups (from a
        backup, which says so even of an empty one); an account with accounts in it is a group anyway."""
        retire_ids = retire_ids or set()
        group_ids = group_ids or set()
        types = types or {}
        accounts = self.ar.list()
        by_id = {a.id: a for a in accounts}
        roots = {a.name: a.id for a in accounts if a.parent_id is None}
        contacts = self.ar.contact_account_ids()
        children: dict[UUID, builtins.list[Account]] = defaultdict(builtins.list)
        for a in accounts:
            if a.parent_id is not None:
                children[a.parent_id].append(a)

        def path(a: Account) -> str:
            names = [a.name]
            while a.parent_id is not None and a.parent_id in by_id:
                a = by_id[a.parent_id]
                names.append(a.name)
            return ":".join(reversed(names))

        def root_name(a: Account) -> str:
            return path(a).split(":")[0]

        def subtree(a: Account) -> builtins.list[Account]:
            out = [a]
            for child in children[a.id]:
                out.extend(subtree(child))
            return out

        keyed = {a.system_key: a for a in accounts if a.system_key}
        retired: dict[UUID, str] = {}  # account → "loan" or "investment"
        for key in RETIRED_KEYS:
            if key in keyed:
                for a in subtree(keyed[key]):
                    retired[a.id] = "loan" if key == "liabilities.loans" else "investment"
        for chosen in retire_ids:
            if chosen in by_id:
                for a in subtree(by_id[chosen]):
                    retired[a.id] = "loan" if root_name(a) == "Liabilities" else "investment"
        holding_roots = {roots.get("Assets"), roots.get("Liabilities")} - {None}
        groups = [
            a
            for a in accounts
            if a.parent_id in holding_roots
            and a.id not in contacts
            and a.id not in retired
            and (a.system_key is not None or a.id in group_ids or children[a.id])
        ]
        group_ids = {a.id for a in groups}
        leaves = [
            a
            for a in accounts
            if a.parent_id is not None
            and a.id not in contacts
            and a.id not in retired
            and a.id not in group_ids
            and root_name(a) in ("Assets", "Liabilities")
        ]
        kept = {a.id for a in leaves}

        work = _Work(
            roots=roots,
            type_groups={key: keyed[key].id if key in keyed else None for key in TYPE_KEYS},
            renames={keyed[k].id: TYPE_NAMES[k] for k in TYPE_KEYS if k in keyed and keyed[k].name != TYPE_NAMES[k]},
        )
        plan = ConversionPlan(strict=strict)
        for group_id, name in work.renames.items():
            plan.moved.append(AccountMove(account_id=group_id, path=path(by_id[group_id]), becomes=f"renamed {name}"))

        # Where each kept account goes.
        taken: dict[str, set[str]] = defaultdict(set)
        for a in leaves:
            parent = by_id[a.parent_id] if a.parent_id else None
            if parent is not None and parent.system_key in TYPE_KEYS:
                taken[parent.system_key].add(a.name.casefold())
        for a in leaves:
            parent = by_id[a.parent_id] if a.parent_id else None
            chosen = types.get(a.id) or (types.get(a.parent_id) if a.parent_id else None)
            if chosen is not None and (chosen not in TYPE_KEYS or TYPE_ROOTS[chosen] != root_name(a)):
                raise ValueError(f"'{path(a)}' cannot be a {TYPE_NAMES.get(chosen, chosen)}!")
            if strict and a.id in off_budget_ids and chosen is None:
                plan.undecided_accounts.append(path(a))
            here = parent.system_key if parent is not None and parent.system_key in TYPE_KEYS else None
            if here is not None and chosen in (None, here):
                work.places.append((a.id, here, a.name))
                continue
            key = chosen or ("assets.bank" if root_name(a) == "Assets" else "liabilities.cards")
            name = a.name
            if name.casefold() in taken[key]:
                name = f"{a.name} ({parent.name if parent else root_name(a)})"[:NAME_LIMIT]
            taken[key].add(name.casefold())
            work.places.append((a.id, key, name))
            plan.moved.append(
                AccountMove(account_id=a.id, path=path(a), becomes=f"{TYPE_ROOTS[key]}:{TYPE_NAMES[key]}:{name}")
            )

        # Categories: found by name and kind among the top-level ones (open or closed) before one is made.
        categories = {c.id: c for c in self.categories.list(include_closed=True)}
        by_name: dict[tuple[str, str], CategoryRead] = {}
        for c in sorted(categories.values(), key=lambda c: c.closed_on is not None):
            if c.parent_id is None:
                by_name.setdefault((c.name.casefold(), c.kind), c)

        def label(line_category: UUID | None, money_in: bool, account: Account) -> tuple[CategoryRef, bool]:
            """The line's category and whether it is one the payment never had."""
            kind = "spending" if money_in else "earning"
            own = categories.get(line_category) if line_category else None
            if own is not None and own.kind == kind:
                if own.closed_on is not None:
                    work.reopen.add(own.id)
                return own.id, False
            if money_in:
                name = account.name
            else:
                name = LOAN_INCOME if retired[account.id] == "loan" else INVESTMENT_INCOME
            existing = by_name.get((name.casefold(), kind))
            if existing is not None:
                if existing.closed_on is not None:
                    work.reopen.add(existing.id)
                return existing.id, True
            work.new_categories.setdefault((name.casefold(), kind), name)
            return (name.casefold(), kind), True

        def where(money_in: bool) -> Target:
            return "Expenses" if money_in else "Income"

        def describe(retargets: builtins.list[tuple[Posting, Target, CategoryRef | None]]) -> str:
            parts = []
            for p, target, ref in retargets:
                shown = (
                    categories[ref].name
                    if isinstance(ref, UUID)
                    else (work.new_categories.get(ref, "") if ref is not None else "")
                )
                parts.append(f"{by_id[p.account_id].name} → {target}" + (f" ({shown})" if shown else ""))
            return ", ".join(parts)

        overspent: set[str] = set()
        postings = self.tr.postings_for_accounts(builtins.list(retired))
        transaction_ids = builtins.list(dict.fromkeys(p.transaction_id for p in postings))
        lines = self.tr.postings_for_transactions(transaction_ids)
        entries = self.tr.read_many(transaction_ids)
        for transaction_id in transaction_ids:
            entry = entries[transaction_id]
            entry_lines = lines.get(transaction_id, [])
            head = f"{entry.date.isoformat()} {entry.payee or 'No payee'}"
            change = EntryChange(transaction_id=transaction_id, day=entry.date, summary=head)
            touches_budget = any(p.account_id in kept for p in entry_lines)
            touches_people = any(p.account_id in contacts for p in entry_lines)
            if not touches_budget and not touches_people:
                plan.deleted.append(change)
                work.deletes.append(transaction_id)
                continue
            if not touches_budget and strict:
                change.summary = f"{head}: a retired account and a person, nothing in the budget"
                plan.undecided_entries.append(change)
                continue
            proposed: builtins.list[tuple[Posting, Target, CategoryRef | None]] = []
            fresh: builtins.list[bool] = []
            sides: dict[UUID | str, set[PostingSide]] = defaultdict(set)
            for p in entry_lines:
                if p.account_id in retired:
                    money_in = p.side == PostingSide.DEBIT
                    ref, new = label(p.category_id, money_in, by_id[p.account_id])
                    proposed.append((p, where(money_in), ref))
                    fresh.append(new and money_in)
                    sides[where(money_in)].add(p.side)
                else:
                    target_key: UUID | str = p.account_id
                    if p.account_id == roots.get("Expenses"):
                        target_key = "Expenses"
                    elif p.account_id == roots.get("Income"):
                        target_key = "Income"
                    sides[target_key].add(p.side)
            if any(len(s) > 1 for s in sides.values()):
                if strict:
                    change.summary = f"{head}: it would put Expenses or Income on both sides"
                    plan.undecided_entries.append(change)
                    continue
                proposed = [(p, "Opening Balances", None) for p, _, _ in proposed]
                fresh = []
            for (p, target, ref), new in zip(proposed, fresh or [False] * len(proposed), strict=True):
                work.retargets.append((p.id, target, ref))
                if new:
                    overspent.add(entry.date.strftime("%Y-%m"))
            change.summary = f"{head}: {describe(proposed)}"
            plan.rewritten.append(change)

        rows = self.rr.postings()
        for rule in self.rr.list():
            rule_rows = rows.get(rule.id, [])
            named = {rule.from_account_id, rule.to_account_id, *(r.account_id for r in rule_rows)} - {None}
            if not named & retired.keys():
                continue
            change = EntryChange(recurring_id=rule.id, summary=f"Recurring {rule.payee or 'rule'}")
            # Every retired account the rule names is replaced (so the account can go), whether or not the rule lives on.
            mapping: dict[UUID, tuple[Target, CategoryRef | None]] = {}
            if rule.from_account_id is not None or rule.to_account_id is not None:
                lives = (rule.to_account_id if rule.from_account_id in retired else rule.from_account_id) in kept
                if rule.to_account_id in retired:
                    ref, _ = label(rule.category_id, True, by_id[rule.to_account_id])
                    mapping[rule.to_account_id] = ("Expenses", ref)
                if rule.from_account_id in retired and rule.from_account_id not in mapping:
                    ref, _ = label(rule.category_id, False, by_id[rule.from_account_id])
                    mapping[rule.from_account_id] = ("Income", ref)
            else:
                lives = any(r.account_id in kept for r in rule_rows)
                for r in rule_rows:
                    if r.account_id in retired and r.account_id not in mapping:
                        money_in = r.side == PostingSide.DEBIT
                        ref, _ = label(r.category_id, money_in, by_id[r.account_id])
                        mapping[r.account_id] = (where(money_in), ref)
            work.rules.append((rule.id, mapping))
            if not lives:
                work.ends.append(rule.id)
                change.summary += ": ended"
                plan.deleted.append(change)
                continue
            change.summary += ": " + ", ".join(f"{by_id[a].name} → {t}" for a, (t, _) in mapping.items())
            plan.rewritten.append(change)

        # What goes: retired accounts and a person's own groups, the deepest first.
        def depth(a: Account) -> int:
            return path(a).count(":")

        for a in sorted((by_id[i] for i in retired), key=depth, reverse=True):
            work.accounts_to_delete.append(a.id)
            work.retired_accounts.append(a.id)
            plan.retired.append(AccountMove(account_id=a.id, path=path(a), becomes="deleted"))
        for a in groups:
            if a.system_key not in TYPE_KEYS:
                work.accounts_to_delete.append(a.id)
                plan.retired.append(AccountMove(account_id=a.id, path=path(a), becomes="deleted (a group)"))

        plan.new_categories = sorted(work.new_categories.values())
        plan.overspent_months = sorted(overspent)
        plan._work = work
        return plan

    def apply(self, plan: ConversionPlan, *, commit: bool = True) -> ConversionResult:
        """Carry `plan` out. `commit=False` leaves the commit to the caller (a restore, which saves everything at once)."""
        work: _Work = plan._work
        if work is None:
            raise ConversionRefused("work out a plan first!")
        if plan.strict and (plan.undecided_accounts or plan.undecided_entries):
            raise ConversionRefused("some accounts or entries need a decision first (see the plan)!")
        result = ConversionResult()

        made: dict[tuple[str, str], UUID] = {}
        for (key, kind), name in work.new_categories.items():
            category = BudgetCategory(user_id=self.ar.uid, name=name, kind=kind)
            made[(key, kind)] = self.categories.cr.add(category).id
            result.categories_made.append(name)
        for category_id in work.reopen:
            reopened = self.categories.cr.read(category_id)
            if reopened is not None:
                reopened.closed_on = None
                self.ar.db.add(reopened)

        def category(ref: CategoryRef | None) -> UUID | None:
            if ref is None or isinstance(ref, UUID):
                return ref
            return made[ref]

        groups: dict[str, UUID] = {}
        for key, group_id in work.type_groups.items():
            if group_id is None:
                created = self.ar.create(AccountBase(name=TYPE_NAMES[key], parent_id=work.roots[TYPE_ROOTS[key]]))
                created.system_key = key
                self.ar.db.add(created)
                group_id = created.id
            groups[key] = group_id
        for group_id, name in work.renames.items():
            self.ar.place(group_id, work.roots[TYPE_ROOTS[_key_of(work, group_id)]], name)
        for account_id, key, name in work.places:
            self.ar.place(account_id, groups[key], name)

        targets = {"Expenses": work.roots["Expenses"], "Income": work.roots["Income"]}
        if any(target == "Opening Balances" for _, target, _ in work.retargets):
            targets["Opening Balances"] = self.accounts.opening_balances_account().id
        for posting_id, target, ref in work.retargets:
            self.tr.retarget_posting(posting_id, targets[target], category(ref))
        result.rewritten = sum(1 for c in plan.rewritten if c.transaction_id is not None)
        self.tr.db.expire_all()
        for transaction_id in work.deletes:
            self.tr.delete(transaction_id)
        result.deleted = len(work.deletes)

        for recurring_id, mapping in work.rules:
            self.rr.retarget(recurring_id, {a: (targets[t], category(ref)) for a, (t, ref) in mapping.items()})
        result.recurring_rewritten = len(work.rules)
        for recurring_id in work.ends:
            self.rr.end(recurring_id)
        result.recurring_ended = len(work.ends)

        # A shared bill a retired account paid towards: the money now comes from Income (Borrowed or Redeemed).
        bills = SharedExpenseRepository(self.ar.db, self.ar.uid)
        for account_id in work.retired_accounts:
            bills.repoint_account(account_id, work.roots["Income"])
        for account_id in work.accounts_to_delete:
            self.ar.delete(account_id)
        result.accounts_deleted = len(work.accounts_to_delete)
        if commit:
            self.ar.db.commit()
        else:
            self.ar.db.flush()
        return result


def _key_of(work: _Work, group_id: UUID) -> str:
    return next(key for key, gid in work.type_groups.items() if gid == group_id)
