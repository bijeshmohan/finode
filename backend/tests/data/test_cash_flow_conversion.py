"""Converting a person's books to cash flow (services/cash_flow.py): investment and loan accounts become categories,
the built-in groups become the four account types, and a person's own groups go. The kept accounts' balances never
move."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from finode.repositories import AccountRepository, ProfileRepository, TransactionRepository
from finode.repositories.recurring import RecurringRepository
from finode.schemas.account import AccountCreate, AccountUpdate, GroupCreate
from finode.schemas.category import CategoryCreate
from finode.schemas.contact import ContactCreate
from finode.schemas.recurring import RecurringCreate
from finode.schemas.transaction import PostingCreate, TransactionCreate
from finode.services import account as account_service
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
    groups = {a.system_key: a.id for a in s.accounts.ar.list() if a.system_key}

    def made(name, key, **extra):
        return s.accounts.create(AccountCreate(name=name, parent_id=groups[key], **extra))

    hdfc = made("HDFC", "assets.bank", balance=Decimal("100000"))
    old_sbi = made("Old SBI", "assets.bank", on_budget=False, balance=Decimal("500"))
    card = made("Amex", "liabilities.cards", statement_day=5, due_day=25)
    loan = made("Home Loan", "liabilities.loans", balance=Decimal("800000"))
    fund = made("Axis Bluechip", "assets.investments")
    wallets = s.accounts.create_group(GroupCreate(name="Wallets", root="Assets", new_accounts_in_budget=True))
    paytm = s.accounts.create(AccountCreate(name="Paytm", parent_id=wallets.id, balance=Decimal("300")))

    emi_cat = s.categories.create(CategoryCreate(name="Home loan EMI", kind="spending"))
    dining = s.categories.create(CategoryCreate(name="Dining", kind="spending"))

    _entry(s, date(2026, 9, 2), "Lender", _line(hdfc.id, "debit", "50000"), _line(loan.id, "credit", "50000"))
    _entry(s, date(2026, 9, 5), "EMI", _line(loan.id, "debit", "15000", emi_cat.id), _line(hdfc.id, "credit", "15000"))
    _entry(s, date(2026, 10, 5), "EMI", _line(loan.id, "debit", "15000"), _line(hdfc.id, "credit", "15000"))
    _entry(s, date(2026, 10, 10), "SIP", _line(fund.id, "debit", "10000"), _line(hdfc.id, "credit", "10000"))
    _entry(s, date(2026, 10, 20), "Redeemed", _line(hdfc.id, "debit", "4000"), _line(fund.id, "credit", "4000"))
    value = s.accounts.opening_balances_account()
    _entry(s, date(2026, 10, 31), "NAV", _line(fund.id, "debit", "650"), _line(value.id, "credit", "650"))
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
        hdfc=hdfc.id, old_sbi=old_sbi.id, card=card.id, loan=loan.id, fund=fund.id, paytm=paytm.id, asha=asha
    )
    return s, ids


@pytest.fixture
def books(session, monkeypatch):
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)
    s, ids = _build(session)

    def off_budget_ids():
        return {a.id for a in s.accounts.ar.list() if not a.on_budget}

    def kept():
        return [ids.hdfc, ids.old_sbi, ids.card, ids.paytm, ids.asha.receivable_account_id]

    days = sorted({t.date for t in s.transactions.list(limit=1000)} | {date(2026, 12, 31)})

    def balances_by_day():
        return {d: {a.id: a.balance for a in s.accounts.list(as_of=d) if a.id in kept()} for d in days}

    def put_old_sbi_in_budget():
        s.accounts.update(ids.old_sbi, AccountUpdate(on_budget=True))

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

    return SimpleNamespace(
        s=s,
        ids=ids,
        conversion=_conversion(session),
        off_budget_ids=off_budget_ids,
        balances_by_day=balances_by_day,
        put_old_sbi_in_budget=put_old_sbi_in_budget,
        lines_of=lines_of,
        session=session,
    )


def _convert(books):
    return books.conversion.apply(books.conversion.plan(books.off_budget_ids(), strict=True))


def test_plan_lists_undecided_excluded_bank(books):
    plan = books.conversion.plan(books.off_budget_ids(), strict=True)
    assert plan.undecided_accounts == ["Assets:Bank Accounts:Old SBI"]


def test_plan_changes_nothing(books):
    before = books.balances_by_day()
    books.conversion.plan(books.off_budget_ids(), strict=True)
    assert books.balances_by_day() == before
    assert any(a.name == "Home Loan" for a in books.s.accounts.ar.list())


def test_apply_refuses_strict_plan_with_undecided(books):
    with pytest.raises(ConversionRefused):
        _convert(books)
    assert any(a.name == "Home Loan" for a in books.s.accounts.ar.list()), "nothing changed"


def test_apply_converts_and_keeps_books_balanced(books):
    books.put_old_sbi_in_budget()
    before = books.balances_by_day()
    result = _convert(books)
    assert books.s.reports.trial_balance().balanced
    assert books.balances_by_day() == before
    names = {a.name for a in books.s.accounts.ar.list()}
    assert {"Bank Account", "Cash", "Credit Card", "Prepaid Wallet"} <= names
    assert not names & {
        "Home Loan",
        "Axis Bluechip",
        "Investments",
        "Loans",
        "Wallets",
        "Bank Accounts",
        "Credit Cards",
    }
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


def test_kept_accounts_are_under_their_types_and_in_the_budget(books):
    books.put_old_sbi_in_budget()
    _convert(books)
    by_id = {a.id: a for a in books.s.accounts.ar.list()}
    parent_key = {i: by_id[by_id[i].parent_id].system_key for i in (books.ids.hdfc, books.ids.card, books.ids.paytm)}
    assert parent_key == {
        books.ids.hdfc: "assets.bank",
        books.ids.card: "liabilities.cards",
        books.ids.paytm: "assets.bank",
    }
    assert all(by_id[i].on_budget for i in (books.ids.hdfc, books.ids.card, books.ids.paytm, books.ids.old_sbi))
    assert by_id[books.ids.asha.receivable_account_id].parent_id == books.s.accounts.ar.root_ids()["Assets"]


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
    plan = books.conversion.plan(books.off_budget_ids(), strict=True)
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


def test_same_root_both_sides_is_undecided(books):
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
    plan = books.conversion.plan(books.off_budget_ids(), strict=True)
    assert [e.summary.split(":")[0] for e in plan.undecided_entries] == ["2026-11-03 Odd"]
    with pytest.raises(ConversionRefused):
        books.conversion.apply(plan)


def test_non_strict_plan_decides_by_default(books):
    before = books.balances_by_day()
    plan = books.conversion.plan(books.off_budget_ids(), strict=False)
    assert plan.undecided_accounts == [] and plan.undecided_entries == []
    books.conversion.apply(plan)
    by_id = {a.id: a for a in books.s.accounts.ar.list()}
    assert by_id[books.ids.old_sbi].on_budget and by_id[by_id[books.ids.old_sbi].parent_id].name == "Bank Account"
    assert books.balances_by_day() == before


def test_overspent_months_listed(books):
    plan = books.conversion.plan(books.off_budget_ids(), strict=True)
    assert plan.overspent_months == ["2026-10"], "the uncategorised EMI and the SIP"


def test_other_person_untouched(books, session):
    other, _ids = _build(session, OTHER_USER)
    books.put_old_sbi_in_budget()
    _convert(books)
    assert {"Home Loan", "Axis Bluechip", "Wallets"} <= {a.name for a in other.accounts.ar.list()}
    assert other.reports.trial_balance().balanced


def test_a_closed_retired_account_is_retired_too(books):
    loans = next(a.id for a in books.s.accounts.ar.list() if a.system_key == "liabilities.loans")
    car = books.s.accounts.create(AccountCreate(name="Car Loan", parent_id=loans))
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
    wallets = next(a for a in books.s.accounts.ar.list() if a.name == "Wallets")
    plan = books.conversion.plan(
        books.off_budget_ids(), strict=True, retire_ids={books.ids.old_sbi}, types={wallets.id: "assets.wallet"}
    )
    assert plan.undecided_accounts == []
    assert "Assets:Wallets:Paytm → Assets:Prepaid Wallet:Paytm" in [f"{m.path} → {m.becomes}" for m in plan.moved]
    books.conversion.apply(plan)
    by_id = {a.id: a for a in books.s.accounts.ar.list()}
    assert books.ids.old_sbi not in by_id
    assert by_id[by_id[books.ids.paytm].parent_id].system_key == "assets.wallet"
    assert (
        books.lines_of("Opening balance").count([("Old SBI", "debit", None), ("Opening Balances", "credit", None)]) == 0
    )


def test_a_chosen_type_puts_an_account_outside_the_budget_in_it(books):
    plan = books.conversion.plan(books.off_budget_ids(), strict=True, types={books.ids.old_sbi: "assets.cash"})
    assert plan.undecided_accounts == []
    books.conversion.apply(plan)
    by_id = {a.id: a for a in books.s.accounts.ar.list()}
    assert by_id[books.ids.old_sbi].on_budget and by_id[by_id[books.ids.old_sbi].parent_id].system_key == "assets.cash"
