"""Converting older books (a restore of a file from before the four types, services/cash_flow.py): investment and loan
accounts become categories, every kept account moves straight under its root with the type of the built-in group it
sat in (or the one chosen for it), the groups go, and no type is ever guessed. The kept accounts' balances never move."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from finode.repositories import AccountRepository, ProfileRepository, TransactionRepository
from finode.repositories.recurring import RecurringRepository
from finode.schemas.account import AccountBase
from finode.schemas.category import CategoryCreate
from finode.schemas.contact import ContactCreate
from finode.schemas.recurring import RecurringCreate
from finode.schemas.transaction import PostingCreate, TransactionCreate
from finode.services.account_types import in_budget
from finode.services.cash_flow import CashFlowConversion, ConversionRefused
from finode.services.contact import ContactService
from finode.services.transaction import TransactionService
from tests.conftest import TEST_USER_ID
from tests.svc import services

OTHER_USER = TEST_USER_ID.__class__("00000000-0000-4000-8000-000000000002")


def _line(account_id=None, side="debit", amount="0", category_id=None):
    return PostingCreate(account_id=account_id, side=side, amount=Decimal(amount), category_id=category_id)


def _entry(s, day, payee, *lines):
    return s.transactions.create(TransactionCreate(date=day, payee=payee, postings=list(lines)))


def _conversion(session, user=TEST_USER_ID):
    s = services(session, user)
    return CashFlowConversion(
        s.accounts, TransactionRepository(session, user), RecurringRepository(session, user), s.categories
    )


def _build(session, user=TEST_USER_ID):
    s = services(session, user)
    s.accounts.ensure_roots()
    ar = s.accounts.ar
    roots = ar.root_ids()
    # The books as a restore writes an old file: the old built-in groups as plain accounts, their keys on the side (no
    # Prepaid Wallet; Investments and Loans outside the budget), a group of the person's own, and an account taken out
    # of the budget.
    groups = {}
    for key, name, root in (
        ("assets.bank", "Bank Accounts", "Assets"),
        ("liabilities.cards", "Credit Cards", "Liabilities"),
        ("assets.investments", "Investments", "Assets"),
        ("liabilities.loans", "Loans", "Liabilities"),
    ):
        groups[key] = ar.create(AccountBase(name=name, parent_id=roots[root]))
    wallets = ar.create(AccountBase(name="Wallets", parent_id=roots["Assets"]))

    def made(name, parent_id, **extra):
        return ar.create(AccountBase(name=name, parent_id=parent_id, **extra))

    hdfc = made("HDFC", groups["assets.bank"].id)
    old_sbi = made("Old SBI", groups["assets.bank"].id)
    card = made("Amex", groups["liabilities.cards"].id, statement_day=5, due_day=25)
    loan = made("Home Loan", groups["liabilities.loans"].id)
    fund = made("Axis Bluechip", groups["assets.investments"].id)
    paytm = made("Paytm", wallets.id)
    session.commit()
    opening = s.accounts.opening_balances_account()
    for account, amount, side in ((hdfc, "100000", "debit"), (old_sbi, "500", "debit"), (paytm, "300", "debit")):
        _entry(
            s, date(2026, 9, 1), "Opening balance", _line(account.id, side, amount), _line(opening.id, "credit", amount)
        )
    _entry(
        s, date(2026, 9, 1), "Opening balance", _line(opening.id, "debit", "800000"), _line(loan.id, "credit", "800000")
    )

    emi_cat = s.categories.create(CategoryCreate(name="Home loan EMI", kind="spending"))
    dining = s.categories.create(CategoryCreate(name="Dining", kind="spending"))

    _entry(s, date(2026, 9, 2), "Lender", _line(hdfc.id, "debit", "50000"), _line(loan.id, "credit", "50000"))
    _entry(s, date(2026, 9, 5), "EMI", _line(loan.id, "debit", "15000", emi_cat.id), _line(hdfc.id, "credit", "15000"))
    _entry(s, date(2026, 10, 5), "EMI", _line(loan.id, "debit", "15000"), _line(hdfc.id, "credit", "15000"))
    _entry(s, date(2026, 10, 10), "SIP", _line(fund.id, "debit", "10000"), _line(hdfc.id, "credit", "10000"))
    _entry(s, date(2026, 10, 20), "Redeemed", _line(hdfc.id, "debit", "4000"), _line(fund.id, "credit", "4000"))
    _entry(s, date(2026, 10, 31), "NAV", _line(fund.id, "debit", "650"), _line(opening.id, "credit", "650"))
    _entry(s, date(2026, 10, 12), "Swiggy", _line(card.id, "credit", "486"), _line(None, "debit", "486", dining.id))

    contacts = ContactService(s.accounts)
    asha = contacts.create(ContactCreate(name="Asha"))
    s_people = TransactionService(  # a plain shared bill; the app's own comes from EntryService
        TransactionRepository(session, user),
        AccountRepository(session, user),
        ProfileRepository(session, user),
        origin="web",
        contacts=True,
    )
    s_people.create(
        TransactionCreate(
            date=date(2026, 10, 14),
            payee="Dinner",
            postings=[
                _line(hdfc.id, "credit", "1000"),
                _line(None, "debit", "500", dining.id),
                _line(asha.receivable_account_id, "debit", "500"),
            ],
        )
    )
    s.recurring.create(
        RecurringCreate(
            from_account_id=hdfc.id,
            to_account_id=fund.id,
            amount=Decimal("10000"),
            payee="SIP",
            start_date=date(2026, 12, 10),
        )
    )
    session.commit()
    ids = SimpleNamespace(
        hdfc=hdfc.id,
        old_sbi=old_sbi.id,
        card=card.id,
        loan=loan.id,
        fund=fund.id,
        paytm=paytm.id,
        wallets=wallets.id,
        asha=asha,
        keys={g.id: key for key, g in groups.items()},
    )
    return s, ids


@pytest.fixture
def books(session, monkeypatch):
    s, ids = _build(session)

    # What was outside the budget before the four types: a restore retires it (the loan and the fund are under
    # Investments and Loans anyway).
    outside = {ids.old_sbi}

    def plan(**extra):
        """The plan a restore makes, the person's own Wallets given a type unless said otherwise."""
        chosen = {"types": {ids.wallets: "assets.wallet"}, "retire_ids": set(outside), **extra}
        return conversion.plan(ids.keys, **chosen)

    def kept():
        return [ids.hdfc, ids.old_sbi, ids.card, ids.paytm, ids.asha.receivable_account_id]

    days = sorted({t.date for t in s.transactions.list(limit=1000)} | {date(2026, 12, 31)})

    def balances_by_day():
        return {d: {a.id: a.balance for a in s.accounts.list(as_of=d) if a.id in kept()} for d in days}

    def put_old_sbi_in_budget():
        outside.discard(ids.old_sbi)

    def lines_of(payee):
        made = [t for t in s.transactions.list(limit=1000) if t.payee == payee]
        by_id = {a.id: a for a in s.accounts.ar.list()}
        cats = {c.id: c for c in s.categories.list(include_closed=True)}
        return [
            sorted(
                (by_id[p.account_id].name, p.side.value, cats[p.category_id].name if p.category_id else None)
                for p in t.postings
            )
            for t in made
        ]

    conversion = _conversion(session)
    return SimpleNamespace(
        s=s,
        ids=ids,
        conversion=conversion,
        plan=plan,
        balances_by_day=balances_by_day,
        put_old_sbi_in_budget=put_old_sbi_in_budget,
        lines_of=lines_of,
        session=session,
    )


def _convert(books, **extra):
    return books.conversion.apply(books.plan(**extra))


def test_an_account_with_no_type_is_undecided(books):
    plan = books.plan(types={})
    assert plan.undecided_accounts == ["Assets:Wallets:Paytm"], "a group of the person's own: no type to give it"


def test_plan_changes_nothing(books):
    before = books.balances_by_day()
    books.plan(types={})
    assert books.balances_by_day() == before
    assert any(a.name == "Home Loan" for a in books.s.accounts.ar.list())


def test_apply_refuses_while_an_account_has_no_type(books):
    with pytest.raises(ConversionRefused, match="These accounts have no type: Assets:Wallets:Paytm."):
        _convert(books, types={})
    assert any(a.name == "Home Loan" for a in books.s.accounts.ar.list()), "nothing changed"


def test_apply_converts_and_keeps_books_balanced(books):
    books.put_old_sbi_in_budget()
    before = books.balances_by_day()
    result = _convert(books)
    assert books.s.reports.trial_balance().balanced
    assert books.balances_by_day() == before
    names = {a.name for a in books.s.accounts.ar.list()}
    assert not names & {
        "Home Loan",
        "Axis Bluechip",
        "Investments",
        "Loans",
        "Wallets",
        "Bank Accounts",
        "Credit Cards",
        "Bank Account",
        "Credit Card",
    }, "no groups and no type accounts"
    assert sorted(result.categories_made) == ["Axis Bluechip", "Borrowed", "Home Loan", "Redeemed"]


def test_lines_land_in_the_right_categories(books):
    books.put_old_sbi_in_budget()
    _convert(books)
    assert books.lines_of("Lender") == [[("HDFC", "debit", None), ("Income", "credit", "Borrowed")]]
    assert sorted(books.lines_of("EMI")) == [
        [("Expenses", "debit", "Home Loan"), ("HDFC", "credit", None)],
        [("Expenses", "debit", "Home loan EMI"), ("HDFC", "credit", None)],
    ]
    assert books.lines_of("SIP") == [[("Expenses", "debit", "Axis Bluechip"), ("HDFC", "credit", None)]]
    assert books.lines_of("Redeemed") == [[("HDFC", "debit", None), ("Income", "credit", "Redeemed")]]
    assert books.lines_of("NAV") == [], "a value update only kept the worth"
    assert sorted(books.lines_of("Opening balance")) == [
        [("HDFC", "debit", None), ("Opening Balances", "credit", None)],
        [("Old SBI", "debit", None), ("Opening Balances", "credit", None)],
        [("Opening Balances", "credit", None), ("Paytm", "debit", None)],
    ], "the loan's opening balance is gone; the kept accounts' stay"


def test_kept_accounts_sit_under_their_roots_with_their_types(books):
    books.put_old_sbi_in_budget()
    _convert(books)
    by_id = {a.id: a for a in books.s.accounts.ar.list()}
    roots = books.s.accounts.ar.root_ids()
    kept = (books.ids.hdfc, books.ids.old_sbi, books.ids.card, books.ids.paytm)
    assert {i: by_id[i].type for i in kept} == {
        books.ids.hdfc: "assets.bank",
        books.ids.old_sbi: "assets.bank",
        books.ids.card: "liabilities.cards",
        books.ids.paytm: "assets.wallet",
    }, "the type of the built-in group each sat in, or the one chosen"
    assert {by_id[i].parent_id for i in kept} <= {roots["Assets"], roots["Liabilities"]}
    assert all(in_budget(by_id[i]) for i in kept)
    asha = by_id[books.ids.asha.receivable_account_id]
    assert asha.parent_id == roots["Assets"] and asha.type is None, "a person's account stays untyped"


def test_recurring_simple_form_is_rewritten(books):
    books.put_old_sbi_in_budget()
    _convert(books)
    (rule,) = books.s.recurring.list()
    by_id = {a.id: a for a in books.s.accounts.ar.list()}
    cats = {c.id: c.name for c in books.s.categories.list()}
    assert (by_id[rule.from_account_id].name, by_id[rule.to_account_id].name, cats[rule.category_id]) == (
        "HDFC",
        "Expenses",
        "Axis Bluechip",
    )


def test_second_run_changes_nothing(books):
    books.put_old_sbi_in_budget()
    _convert(books)
    before = books.balances_by_day()
    plan = books.conversion.plan({})
    assert (plan.retired, plan.moved, plan.rewritten, plan.deleted, plan.new_categories) == ([], [], [], [], [])
    result = books.conversion.apply(plan)
    assert (result.rewritten, result.deleted, result.accounts_deleted, result.categories_made) == (0, 0, 0, [])
    assert books.balances_by_day() == before


def test_existing_category_names_are_reused(books):
    made = books.s.categories.create(CategoryCreate(name="Borrowed", kind="earning"))
    books.s.categories.delete(made.id)  # unused: gone; make it again and close it with history instead
    again = books.s.categories.create(CategoryCreate(name="borrowed", kind="earning"))
    books.s.categories.close(again.id)
    books.put_old_sbi_in_budget()
    result = _convert(books)
    assert "Borrowed" not in result.categories_made
    borrowed = [c for c in books.s.categories.list(include_closed=True) if c.name.lower() == "borrowed"]
    assert len(borrowed) == 1 and borrowed[0].closed_on is None, "reused and reopened"


def test_an_entry_on_both_sides_of_a_root_posts_to_opening_balances(books):
    refunds = books.s.categories.create(CategoryCreate(name="Refunds", kind="spending"))
    _entry(
        books.s,
        date(2026, 11, 3),
        "Odd",
        _line(books.ids.loan, "debit", "1000"),
        _line(None, "credit", "200", refunds.id),
        _line(books.ids.hdfc, "credit", "800"),
    )
    books.put_old_sbi_in_budget()
    before = books.balances_by_day()
    _convert(books)
    assert sorted(books.lines_of("Odd")[0]) == [
        ("Expenses", "credit", "Refunds"),
        ("HDFC", "credit", None),
        ("Opening Balances", "debit", None),
    ]
    assert books.balances_by_day() == before


def test_overspent_months_listed(books):
    plan = books.plan()
    assert plan.overspent_months == ["2026-10"], "the uncategorised EMI and the SIP"


def test_other_person_untouched(books, session):
    other, _ids = _build(session, OTHER_USER)
    books.put_old_sbi_in_budget()
    _convert(books)
    assert {"Home Loan", "Axis Bluechip", "Wallets"} <= {a.name for a in other.accounts.ar.list()}
    assert other.reports.trial_balance().balanced


def test_a_closed_retired_account_is_retired_too(books):
    loans = next(i for i, key in books.ids.keys.items() if key == "liabilities.loans")
    car = books.s.accounts.ar.create(AccountBase(name="Car Loan", parent_id=loans))
    books.session.commit()
    _entry(books.s, date(2026, 8, 1), "Car", _line(books.ids.hdfc, "debit", "1000"), _line(car.id, "credit", "1000"))
    _entry(
        books.s, date(2026, 8, 9), "Car EMI", _line(car.id, "debit", "1000"), _line(books.ids.hdfc, "credit", "1000")
    )
    books.s.accounts.close(car.id, today=date(2026, 11, 1))
    books.put_old_sbi_in_budget()
    _convert(books)
    assert "Car Loan" not in {a.name for a in books.s.accounts.ar.list()}
    assert books.lines_of("Car") == [[("HDFC", "debit", None), ("Income", "credit", "Borrowed")]]
    assert books.lines_of("Car EMI") == [[("Expenses", "debit", "Car Loan"), ("HDFC", "credit", None)]]


def test_chosen_accounts_are_retired_and_chosen_types_kept(books):
    plan = books.plan(retire_ids={books.ids.old_sbi})
    assert plan.undecided_accounts == []
    assert "Assets:Wallets:Paytm → Assets:Paytm" in [f"{m.path} → {m.becomes}" for m in plan.moved]
    books.conversion.apply(plan)
    by_id = {a.id: a for a in books.s.accounts.ar.list()}
    assert books.ids.old_sbi not in by_id
    assert by_id[books.ids.paytm].type == "assets.wallet"
    assert (
        books.lines_of("Opening balance").count([("Old SBI", "debit", None), ("Opening Balances", "credit", None)]) == 0
    )


def test_a_chosen_type_wins_over_the_group(books):
    books.put_old_sbi_in_budget()
    _convert(books, types={books.ids.wallets: "assets.wallet", books.ids.old_sbi: "assets.cash"})
    by_id = {a.id: a for a in books.s.accounts.ar.list()}
    assert by_id[books.ids.old_sbi].type == "assets.cash" and in_budget(by_id[books.ids.old_sbi])


def test_a_type_that_does_not_fit_the_root_is_refused(books):
    with pytest.raises(ValueError, match="cannot be a Credit Card"):
        books.plan(types={books.ids.wallets: "liabilities.cards"})


def test_a_shared_bill_paid_from_a_retired_account_points_at_where_the_money_now_comes_from(books, session):
    from sqlmodel import select

    from finode.models.contact import ExpenseContribution, SharedExpense

    bill = SharedExpense(
        user_id=TEST_USER_ID,
        description="Dinner",
        date=date(2026, 10, 14),
        total_amount=Decimal("1000"),
        split_method="equal",
        status="draft",
    )
    session.add(bill)
    session.flush()
    session.add(
        ExpenseContribution(
            user_id=TEST_USER_ID,
            shared_expense_id=bill.id,
            is_self=True,
            account_id=books.ids.loan,
            amount=Decimal("1000"),
        )
    )
    session.commit()
    books.put_old_sbi_in_budget()
    _convert(books)
    session.expire_all()
    paid_from = {c.account_id for c in session.exec(select(ExpenseContribution)).all()}
    accounts = {a.id: a for a in books.s.accounts.ar.list()}
    assert books.ids.loan not in paid_from and paid_from <= set(accounts), "no row names a deleted account"
    assert {accounts[a].name for a in paid_from} == {"Income"}, "the money came out of the loan: Borrowed, an income"
