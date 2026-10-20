"""Random sequences of ledger operations, checked after every step against an independent recount.

The services may refuse an operation (a closed account, a locked period, a group that cannot be posted to): that is
fine. What may never happen is an error other than a refusal, an unbalanced book, or a balance that differs from the
one worked out here straight from the stored postings.
"""

import json
import random
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select

from app.auth import CurrentUser, require_authenticated_user
from app.clock import local_today
from app.main import app
from app.models.account import Account
from app.models.transaction import Posting, PostingSide, Transaction
from app.schemas import AccountCreate, AccountUpdate
from app.schemas.transaction import PostingCreate, TransactionCreate, TransactionUpdate

from .conftest import TEST_USER_ID
from .svc import services

NORMAL_DEBIT = {"Assets", "Expenses"}
OTHER = UUID("00000000-0000-4000-8000-0000000000cc")


def money(rng: random.Random) -> Decimal:
    return Decimal(rng.randint(1, 500000)) / 100


def split(rng: random.Random, total: Decimal, parts: int) -> list[Decimal]:
    cuts = sorted(rng.sample(range(1, int(total * 100)), parts - 1)) if parts > 1 and total > Decimal("0.02") * parts else []
    edges = [0, *cuts, int(total * 100)]
    return [Decimal(b - a) / 100 for a, b in zip(edges, edges[1:])]


def recount(session) -> dict[UUID, Decimal]:
    """Every account's balance up to today, from the stored postings only."""
    accounts = {a.aid: a for a in session.exec(select(Account).where(Account.user == TEST_USER_ID)).all()}
    dates = {t.tid: t.date for t in session.exec(select(Transaction).where(Transaction.user == TEST_USER_ID)).all()}

    def root(account: Account) -> str:
        while account.parent_id is not None:
            account = accounts[account.parent_id]
        return account.name

    own: dict[UUID, Decimal] = {aid: Decimal(0) for aid in accounts}
    for p in session.exec(select(Posting).where(Posting.user == TEST_USER_ID)).all():
        if dates[p.transaction] > local_today():
            continue
        debit_side = root(accounts[p.account]) in NORMAL_DEBIT
        own[p.account] += p.amount if (p.side == PostingSide.DEBIT) == debit_side else -p.amount
    total = dict(own)
    for aid, account in accounts.items():
        parent = account.parent_id
        while parent is not None:
            total[parent] += own[aid]
            parent = accounts[parent].parent_id
    return total


def check(session, s, step: str) -> None:
    trial = s.reports.trial_balance()
    assert trial.balanced and not trial.problems, (step, trial.problems)
    expected = recount(session)
    for account in s.accounts.list():
        assert account.balance == expected[account.aid], (step, account.name, account.balance, expected[account.aid])
    raw = session.exec(select(Posting).where(Posting.user == TEST_USER_ID)).all()
    assert sum(p.amount for p in raw if p.side == PostingSide.DEBIT) == sum(p.amount for p in raw if p.side == PostingSide.CREDIT)
    assert all(p.amount > 0 for p in raw)


def run(session, seed: int, steps: int) -> list[str]:
    rng = random.Random(seed)
    s = services(session)
    s.accounts.list()
    roots = {a.name: a.aid for a in s.accounts.list() if a.parent_id is None}
    log: list[str] = []
    made = 0

    def accounts():
        return [a for a in s.accounts.list() if a.parent_id is not None]

    def pick_postings():
        pool = accounts()
        if len(pool) < 2:
            return None
        chosen = rng.sample(pool, rng.randint(2, min(4, len(pool))))
        debit_n = rng.randint(1, len(chosen) - 1)
        total = money(rng)
        debits, credits = split(rng, total, debit_n), split(rng, total, len(chosen) - debit_n)
        rows = [PostingCreate(account=a.aid, side=PostingSide.DEBIT, amount=x) for a, x in zip(chosen[:debit_n], debits)]
        rows += [PostingCreate(account=a.aid, side=PostingSide.CREDIT, amount=x) for a, x in zip(chosen[debit_n:], credits)]
        return rows

    def when():
        return local_today() + timedelta(days=rng.randint(-60, 25))

    for step in range(steps):
        op = rng.choice(
            ["account"] * 3 + ["tx"] * 8 + ["edit"] * 3 + ["delete"] * 2 + ["restore"] * 2 + ["balance"] * 2
            + ["rename", "move", "close", "reopen", "drop", "undrop"]
        )
        label = f"seed {seed} step {step} {op}"
        s = services(session)
        try:
            if op == "account":
                made += 1
                parent = rng.choice([*roots.values(), *[a.aid for a in accounts() if a.parent_id in roots.values()]])
                s.accounts.create(AccountCreate(name=f"A{made}", parent_id=parent, balance=rng.choice([Decimal(0), money(rng)])))
            elif op == "tx":
                rows = pick_postings()
                if rows:
                    s.transactions.create(TransactionCreate(date=when(), payee=f"p{step}", postings=rows))
            elif op in ("edit", "delete"):
                found = s.transactions.list(limit=50)
                if found:
                    t = rng.choice(found)
                    if op == "delete":
                        s.transactions.delete(t.tid)
                    else:
                        rows = pick_postings()
                        s.transactions.update(t.tid, TransactionUpdate(date=when(), payee=f"e{step}", postings=rows))
            elif op == "restore":
                options = s.transactions.restorable()
                if options:
                    s.transactions.restore(rng.choice(options).hid)
            elif op == "balance":
                pool = [a for a in accounts() if a.parent_id in roots.values() or True]
                if pool:
                    s.accounts.update(rng.choice(pool).aid, AccountUpdate(balance=money(rng) * rng.choice([1, -1])))
            elif op == "rename":
                pool = accounts()
                if pool:
                    s.accounts.update(rng.choice(pool).aid, AccountUpdate(name=f"R{step}"))
            elif op == "move":
                pool = accounts()
                if len(pool) > 1:
                    a, b = rng.sample(pool, 2)
                    s.accounts.update(a.aid, AccountUpdate(parent_id=b.aid))
            elif op in ("close", "reopen"):
                pool = accounts()
                if pool:
                    getattr(s.accounts, op)(rng.choice(pool).aid)
            elif op == "drop":
                pool = accounts()
                if pool:
                    s.accounts.delete(rng.choice(pool).aid)
            elif op == "undrop":
                options = s.accounts.restorable()
                if options:
                    s.accounts.restore_deleted(rng.choice(options)["did"])
            log.append(f"{label}: ok")
        except ValueError as refusal:
            session.rollback()
            log.append(f"{label}: refused ({str(refusal)[:50]})")
        check(session, services(session), label)
    return log


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_random_operations_keep_the_books_exact(session, seed):
    log = run(session, seed, steps=120)
    assert sum(1 for line in log if line.endswith("ok")) > 40, "the run should mostly do things, not be refused"


def test_a_random_ledger_survives_a_backup_and_restore(session, client):
    run(session, 11, steps=150)
    doc = client.get("/api/backup").json()

    def balances():
        return {a["name"] + "|" + str(a["parent_id"] is None): a["balance"] for a in client.get("/api/accounts/").json()}

    before = sorted(a["balance"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None)
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(id=OTHER, email="o@example.com", claims={})
    try:
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert done.status_code == 200, done.text
        after = sorted(a["balance"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None)
        assert client.get("/api/reports/trial-balance").json()["balanced"]
        assert before == after
    finally:
        app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(id=TEST_USER_ID, email="test@example.com", claims={})


# ---- the budget -----------------------------------------------------------------------------------------------


def month_of(day):
    return day.replace(day=1)


def budget_checks(session, s, label: str) -> None:
    from app.models.budget import BudgetAllocation

    today = month_of(local_today())
    rows = session.exec(select(BudgetAllocation).where(BudgetAllocation.user == TEST_USER_ID)).all()
    for offset in (-2, -1, 0, 1, 2):
        month = month_of(today + timedelta(days=31 * offset))
        view = s.budget.view(month)
        assert view.ready_to_assign == (
            view.money_in_accounts - view.reserved_for_cards - view.available - view.saving_available
            - view.assigned_to_later_months
        ), (label, month, "Ready to assign must be what is in the accounts minus what already has a job")
        assert view.saving_available == sum((line.available for line in view.saving), Decimal(0)), (label, month)
        earn = {line.aid for line in view.earning}
        assert view.earning_expected == sum((r.amount for r in rows if r.month == month and r.account_id in earn), Decimal(0)), (label, month, "expected income is this month's plan rows only")
        assert view.assigned_to_later_months == sum((r.amount for r in rows if r.month > month and r.account_id not in earn), Decimal(0)), (label, month)


def run_budget(session, seed: int, steps: int) -> int:
    rng = random.Random(seed)
    s = services(session)
    roots = {a.name: a.aid for a in s.accounts.list() if a.parent_id is None}
    bank = s.accounts.create(AccountCreate(name="Bank", parent_id=roots["Assets"], balance=Decimal(5000)))
    card = s.accounts.create(AccountCreate(name="Card", parent_id=roots["Liabilities"], on_budget=True))
    salary = s.accounts.create(AccountCreate(name="Salary", parent_id=roots["Income"]))
    cats = [s.accounts.create(AccountCreate(name=n, parent_id=roots["Expenses"])) for n in ("Rent", "Food", "Fun", "Bills")]
    fund = s.accounts.create(AccountCreate(name="Fund", parent_id=roots["Assets"], saving=True))
    assert not fund.on_budget and fund.saving, "an account planned for saving starts outside the budget"
    done = 0
    for step in range(steps):
        s = services(session)
        month = month_of(local_today() + timedelta(days=31 * rng.randint(-2, 2)))
        op = rng.choice(["assign"] * 4 + ["move"] * 3 + ["spend"] * 4 + ["card"] * 2 + ["income"] + ["copy", "fund", "target"] + ["assign_save", "save", "save", "withdraw", "assign_earn"])
        label = f"budget seed {seed} step {step} {op}"
        try:
            if op == "assign":
                cat = rng.choice(cats)
                before = {l.name: l.available for l in s.budget.view(month).lines}[cat.name]
                amount = money(rng) * rng.choice([1, 1, 1, -1])
                view = s.budget.assign(month, cat.aid, amount)
                after = {l.name: l.available for l in view.lines}[cat.name]
                assert amount >= 0 or after >= 0 or before < 0, (label, "taking money out never leaves a category overspent")
            elif op == "assign_earn":
                s.budget.assign(month, salary.aid, money(rng))
            elif op == "assign_save":
                s.budget.assign(month, fund.aid, money(rng) * rng.choice([1, 1, -1]))
            elif op in ("save", "withdraw"):
                amount = money(rng) / 5
                into, out = (fund, bank) if op == "save" else (bank, fund)
                s.transactions.create(TransactionCreate(date=month + timedelta(days=rng.randint(0, 27)), postings=[
                    PostingCreate(account=into.aid, side=PostingSide.DEBIT, amount=amount),
                    PostingCreate(account=out.aid, side=PostingSide.CREDIT, amount=amount)]))
            elif op == "move":
                a, b = rng.sample([*cats, fund], 2)
                before = s.budget.view(month).ready_to_assign
                s.budget.move(month, a.aid, b.aid, money(rng) / 10)
                assert s.budget.view(month).ready_to_assign == before, (label, "moving money never changes Ready to assign")
            elif op in ("spend", "card"):
                source = bank if op == "spend" else card
                day = month + timedelta(days=rng.randint(0, 27))
                amount = money(rng) / 5
                s.transactions.create(TransactionCreate(date=day, postings=[
                    PostingCreate(account=rng.choice(cats).aid, side=PostingSide.DEBIT, amount=amount),
                    PostingCreate(account=source.aid, side=PostingSide.CREDIT, amount=amount)]))
            elif op == "income":
                amount = money(rng)
                s.transactions.create(TransactionCreate(date=month + timedelta(days=rng.randint(0, 27)), postings=[
                    PostingCreate(account=bank.aid, side=PostingSide.DEBIT, amount=amount),
                    PostingCreate(account=salary.aid, side=PostingSide.CREDIT, amount=amount)]))
            elif op == "copy":
                s.budget.copy_previous(month)
            elif op == "fund":
                s.budget.fund(month)
            elif op == "target":
                kind = rng.choice(["monthly", "refill", "by_date", "weekly", "yearly"])
                s.budget.set_target(rng.choice(cats).aid, kind, money(rng), month + timedelta(days=60), rng.randint(0, 6))
            done += 1
        except ValueError:
            session.rollback()
        budget_checks(session, services(session), label)
    return done


@pytest.mark.parametrize("seed", [21, 22, 23, 24])
def test_the_budget_adds_up_whatever_is_assigned_moved_or_spent(session, seed):
    assert run_budget(session, seed, steps=70) > 20  # a share of the operations is refused on purpose
