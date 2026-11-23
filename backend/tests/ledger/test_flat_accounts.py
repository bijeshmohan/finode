"""Every account sits straight under Assets or Liabilities and carries its type (Bank Account, Cash, Credit Card,
Prepaid Wallet) as a column: there are no type accounts in the tree, and finode never picks a type for anyone."""

from decimal import Decimal

import pytest

from finode.models import Account
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


def _make(s, name, key, **extra):
    return s.accounts.create(AccountCreate(name=name, type=key, **extra))


def _roots(s):
    return s.accounts.ar.root_ids()


def test_a_new_account_sits_under_its_root_with_its_type(s):
    hdfc = _make(s, "HDFC", "assets.bank")
    amex = _make(s, "Amex", "liabilities.cards")
    roots = _roots(s)
    assert hdfc.parent_id == roots["Assets"] and hdfc.type == "assets.bank"
    assert amex.parent_id == roots["Liabilities"] and amex.type == "liabilities.cards"
    by_id = {a.id: a for a in s.accounts.ar.list()}
    assert by_id[hdfc.id].type == "assets.bank", "the type is the account's own column"


def test_no_type_accounts_are_made(s):
    names = sorted((a.name, a.parent_id is None) for a in s.accounts.ar.list())
    assert names == [(n, True) for n in ("Assets", "Equity", "Expenses", "Income", "Liabilities")]
    assert "system_key" not in Account.model_fields


def test_names_are_unique_per_root_whatever_the_type(s):
    _make(s, "Paytm", "assets.cash")
    with pytest.raises(ValueError, match="Assets already has an account called 'Paytm'!"):
        _make(s, "paytm", "assets.wallet")
    _make(s, "Paytm", "liabilities.cards")  # another root: fine
    _make(s, "HDFC", "assets.bank")
    sbi = _make(s, "SBI", "assets.bank")
    with pytest.raises(ValueError, match="Assets already has an account called 'HDFC'!"):
        s.accounts.update(sbi.id, AccountUpdate(name="hdfc"))


def test_an_account_holds_no_accounts(s):
    hdfc = _make(s, "HDFC", "assets.bank")
    sbi = s.accounts.create(AccountCreate.model_validate({"name": "SBI", "type": "assets.bank", "parent_id": hdfc.id}))
    assert sbi.parent_id == _roots(s)["Assets"], "an old client's parent_id is not read"


def test_create_without_a_type_is_refused(client):
    assert client.post("/api/accounts/", json={"name": "Loose"}).status_code == 422


def test_type_and_budget_come_from_the_column(s):
    made = {key: _make(s, f"A {key}", key) for key in TYPE_KEYS}
    ContactService(s.accounts).create(ContactCreate(name="Asha"))
    by_id = {a.id: a for a in s.accounts.ar.list()}
    assert {key: type_key(by_id[a.id]) for key, a in made.items()} == {key: key for key in TYPE_KEYS}
    assert all(in_budget(by_id[a.id]) for a in made.values())
    owed = [by_id[i] for i in s.accounts.ar.contact_account_ids()]
    assert len(owed) == 2 and not any(in_budget(a) or type_key(a) for a in owed)
    assert {a.parent_id for a in owed} <= set(_roots(s).values()), "a person's accounts sit under the roots too"


def test_accounts_of_different_types_do_not_merge(s):
    wallet = _make(s, "Wallet", "assets.cash")
    hdfc = _make(s, "HDFC", "assets.bank")
    with pytest.raises(ValueError, match="same type"):
        s.accounts.merge(wallet.id, hdfc.id, dry_run=True)
    sbi = _make(s, "SBI", "assets.bank")
    assert s.accounts.merge(sbi.id, hdfc.id, dry_run=True) is not None


def test_untyped_lists_what_needs_a_type(s):
    ContactService(s.accounts).create(ContactCreate(name="Asha"))
    loose = Account(name="Loose", parent_id=_roots(s)["Assets"], user_id=s.accounts.ar.uid)
    s.accounts.ar.db.add(loose)
    s.accounts.ar.db.commit()
    assert [a.name for a in s.accounts.untyped(s.accounts.ar.list())] == ["Loose"]


def test_a_wallet_counts_as_cash_and_a_card_as_owed(s):
    _make(s, "Paytm", "assets.wallet", balance=Decimal("500"))
    _make(s, "Amex", "liabilities.cards", balance=Decimal("200"))
    assert s.budget.view().cash == Decimal("300.00")
    assert s.reports.summary().cash_on_hand == Decimal("300.00")
