"""Every account a person adds is one of four types (Cash, Bank Account, Credit Card, Prepaid Wallet) and part of the
budget because of it; a person's own groups, accounts straight under a root, and accounts outside the budget are gone."""

from decimal import Decimal

import pytest

from finode.schemas.account import AccountCreate, AccountUpdate
from finode.schemas.contact import ContactCreate
from finode.services.account_types import TYPE_KEYS, in_budget, type_key
from finode.services.contact import ContactService
from tests.svc import services


@pytest.fixture
def s(session):
    s = services(session)
    s.accounts.ensure_roots()
    return s


def _group(s, key):
    return next(a for a in s.accounts.ar.list() if a.system_key == key)


def _make(s, name, key, **extra):
    return s.accounts.create(AccountCreate(name=name, type=key, **extra))


def test_a_new_person_gets_the_four_types(s):
    roots = s.accounts.ar.root_ids()
    groups = [a for a in s.accounts.ar.list() if a.system_key]
    assert sorted((a.system_key, a.name) for a in groups) == [
        ("assets.bank", "Bank Account"),
        ("assets.cash", "Cash"),
        ("assets.wallet", "Prepaid Wallet"),
        ("liabilities.cards", "Credit Card"),
    ], "no Investments or Loans"
    assert {a.parent_id for a in groups if a.system_key == "liabilities.cards"} == {roots["Liabilities"]}


def test_someone_missing_a_type_gets_it(s):
    s.accounts.ar.delete(_group(s, "assets.wallet").id)
    s.accounts.ar.db.commit()
    s.accounts.ensure_roots()
    assert _group(s, "assets.wallet").name == "Prepaid Wallet"


def test_the_type_is_required_and_one_of_four():
    with pytest.raises(ValueError):
        AccountCreate.model_validate({"name": "Loose"})
    with pytest.raises(ValueError):
        AccountCreate.model_validate({"name": "Fund", "type": "assets.investments"})


def test_every_type_is_in_the_budget_and_people_are_not(s):
    made = {key: _make(s, f"A {key}", key) for key in TYPE_KEYS}
    ContactService(s.accounts).create(ContactCreate(name="Asha"))
    by_id = {a.id: a for a in s.accounts.ar.list()}
    assert all(in_budget(by_id[a.id], by_id) for a in made.values())
    assert {key: type_key(by_id[a.id], by_id) for key, a in made.items()} == {key: key for key in TYPE_KEYS}
    assert {key: a.type for key, a in made.items()} == {key: key for key in TYPE_KEYS}, "the read model says so too"
    owed = [by_id[i] for i in s.accounts.ar.contact_account_ids()]
    assert len(owed) == 2 and not any(in_budget(a, by_id) for a in owed)


def test_an_update_cannot_move_an_account_or_take_it_out_of_the_budget(s):
    hdfc = _make(s, "HDFC", "assets.bank")
    s.accounts.update(hdfc.id, AccountUpdate.model_validate({"parent_id": str(_group(s, "assets.cash").id)}))
    s.accounts.update(hdfc.id, AccountUpdate.model_validate({"on_budget": False}))
    again = s.accounts.read(hdfc.id)
    assert again is not None and again.type == "assets.bank", "the old fields are no longer read"


def test_a_prepaid_wallet_counts_as_cash_in_the_budget(s):
    _make(s, "Paytm", "assets.wallet", balance=Decimal("500"))
    _make(s, "Amex", "liabilities.cards", balance=Decimal("200"))
    assert s.budget.view().cash == Decimal("300.00"), "a wallet's money counts, a card's debt is taken off"


def test_cash_on_hand_replaces_net_worth(s):
    _make(s, "HDFC", "assets.bank", balance=Decimal("1000"))
    _make(s, "Paytm", "assets.wallet", balance=Decimal("50"))
    _make(s, "Amex", "liabilities.cards", balance=Decimal("200"))
    summary = s.reports.summary()
    assert summary.cash_on_hand == Decimal("850.00")
    assert "net_worth" not in summary.model_dump()


def test_merging_across_types_of_one_root(s):
    hdfc = _make(s, "HDFC", "assets.bank")
    paytm = _make(s, "Paytm", "assets.wallet")
    assert s.accounts.merge(paytm.id, hdfc.id, dry_run=True) is not None
