"""The flat migration: every account moves from its type's own account straight under its root, with the type as a
column; the type accounts and categories' parents go. It refuses, changing nothing, while an account has no type, sits
deeper than root › account, would clash with another under its root, or a category still has a parent. The downgrade
rebuilds the type accounts."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from finode.config import settings

USER = "00000000-0000-4000-8000-0000000000aa"
BEFORE = "f9b1d3e5a7c0"
AFTER = "a1c3e5f7b9d2"
NOW = "2026-01-01 00:00:00"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    command.upgrade(Config("alembic.ini"), BEFORE)
    yield Config("alembic.ini"), engine
    engine.dispose()


def _id(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012x}"


def _account(connection, key, name, parent=None, system_key=None, closed=None):
    connection.execute(
        sa.text(
            "INSERT INTO accounts (id, user_id, name, parent_id, system_key, closed_on, bill_rounding, pinned, created, "
            "updated) VALUES (:id, :u, :n, :p, :k, :c, 'none', 0, :t, :t)"
        ),
        {"id": key, "u": USER, "n": name, "p": parent, "k": system_key, "c": closed, "t": NOW},
    )


def _books(engine, extra=None):
    """Roots, the four type accounts, HDFC (Bank Account), a closed Amex (Credit Card), a person's account, and one
    entry between HDFC and Amex."""
    ids = {
        name: _id(n)
        for n, name in enumerate(
            ["Assets", "Liabilities", "Equity", "Bank", "Cash", "Card", "Wallet", "HDFC", "Amex", "Asha", "Opening"],
            start=1,
        )
    }
    with engine.begin() as c:
        c.exec_driver_sql("PRAGMA foreign_keys=OFF")
        for root in ("Assets", "Liabilities", "Equity"):
            _account(c, ids[root], root)
        _account(c, ids["Opening"], "Opening Balances", ids["Equity"])
        _account(c, ids["Bank"], "Bank Account", ids["Assets"], "assets.bank")
        _account(c, ids["Cash"], "Cash", ids["Assets"], "assets.cash")
        _account(c, ids["Card"], "Credit Card", ids["Liabilities"], "liabilities.cards")
        _account(c, ids["Wallet"], "Prepaid Wallet", ids["Assets"], "assets.wallet")
        _account(c, ids["HDFC"], "HDFC", ids["Bank"])
        _account(c, ids["Amex"], "Amex", ids["Card"], closed="2026-06-01")
        _account(c, ids["Asha"], "Due from Asha", ids["Assets"])
        c.execute(
            sa.text("INSERT INTO contacts (id, user_id, name, created, updated) VALUES (:id, :u, 'Asha', :t, :t)"),
            {"id": _id(0xC1), "u": USER, "t": NOW},
        )
        c.execute(
            sa.text(
                "INSERT INTO contact_accounts (id, user_id, contact_id, account_id, role, created) "
                "VALUES (:id, :u, :c, :a, 'receivable', :t)"
            ),
            {"id": _id(0xC2), "u": USER, "c": _id(0xC1), "a": ids["Asha"], "t": NOW},
        )
        c.execute(
            sa.text(
                "INSERT INTO transactions (id, user_id, date, created, updated) VALUES (:id, :u, '2026-02-01', :t, :t)"
            ),
            {"id": _id(0xD1), "u": USER, "t": NOW},
        )
        for n, (account, side) in enumerate(((ids["HDFC"], "DEBIT"), (ids["Amex"], "CREDIT")), start=0xD2):
            c.execute(
                sa.text(
                    "INSERT INTO postings (id, user_id, transaction_id, account_id, side, amount, created, updated) "
                    "VALUES (:id, :u, :x, :a, :s, 250, :t, :t)"
                ),
                {"id": _id(n), "u": USER, "x": _id(0xD1), "a": account, "s": side, "t": NOW},
            )
        if extra:
            extra(c, ids)
    return ids


def _rows(engine, sql):
    with engine.connect() as c:
        return c.execute(sa.text(sql)).all()


def _version(engine):
    return _rows(engine, "SELECT version_num FROM alembic_version")[0][0]


def test_accounts_move_up_and_keep_their_type(alembic):
    config, engine = alembic
    ids = _books(engine)
    before = _rows(engine, "SELECT account_id, side, amount FROM postings ORDER BY id")
    command.upgrade(config, AFTER)
    by_name = {r.name: r for r in _rows(engine, "SELECT id, name, parent_id, type, closed_on FROM accounts")}
    assert not {"Bank Account", "Cash", "Credit Card", "Prepaid Wallet"} & set(by_name), "the type accounts go"
    assert (by_name["HDFC"].type, str(by_name["HDFC"].parent_id)) == ("assets.bank", ids["Assets"])
    assert (by_name["Amex"].type, str(by_name["Amex"].parent_id)) == ("liabilities.cards", ids["Liabilities"])
    assert by_name["Amex"].closed_on is not None, "a closed account stays closed"
    assert by_name["Due from Asha"].type is None and by_name["Opening Balances"].type is None
    columns = {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
    assert "system_key" not in columns and "type" in columns
    assert "parent_id" not in {c["name"] for c in sa.inspect(engine).get_columns("budget_categories")}
    assert _rows(engine, "SELECT account_id, side, amount FROM postings ORDER BY id") == before


def _refuses(alembic, extra, message):
    config, engine = alembic
    _books(engine, extra)
    with pytest.raises(RuntimeError, match=message):
        command.upgrade(config, AFTER)
    assert _version(engine) == BEFORE, "nothing was changed"
    assert "system_key" in {c["name"] for c in sa.inspect(engine).get_columns("accounts")}


def test_a_name_clash_refuses_and_changes_nothing(alembic):
    _refuses(
        alembic,
        lambda c, ids: (_account(c, _id(0x51), "Paytm", ids["Cash"]), _account(c, _id(0x52), "paytm", ids["Wallet"])),
        "Paytm under Assets twice: rename one first",
    )


def test_an_untyped_account_refuses(alembic):
    _refuses(
        alembic,
        lambda c, ids: _account(c, _id(0x53), "Loose", ids["Assets"]),
        "give these accounts a type first: Assets:Loose",
    )


def test_something_deeper_refuses(alembic):
    _refuses(
        alembic,
        lambda c, ids: _account(c, _id(0x54), "Sub", ids["HDFC"]),
        "an account holds no accounts: Assets:Bank Account:HDFC:Sub",
    )


def test_a_subcategory_refuses(alembic):
    def subcategory(c, ids):
        for n, name, parent in ((0x61, "Food", None), (0x62, "Dairy", _id(0x61))):
            c.execute(
                sa.text(
                    "INSERT INTO budget_categories (id, user_id, name, kind, parent_id, created, updated) "
                    "VALUES (:id, :u, :n, 'spending', :p, :t, :t)"
                ),
                {"id": _id(n), "u": USER, "n": name, "p": parent, "t": NOW},
            )

    _refuses(alembic, subcategory, "flatten categories first: Dairy")


def test_downgrade_rebuilds_the_types(alembic):
    config, engine = alembic
    ids = _books(engine)
    command.upgrade(config, AFTER)
    command.downgrade(config, BEFORE)
    rows = _rows(engine, "SELECT id, name, parent_id, system_key FROM accounts")
    by_name = {r.name: r for r in rows}
    keyed = {r.system_key: r for r in rows if r.system_key}
    assert set(keyed) == {"assets.bank", "assets.cash", "liabilities.cards", "assets.wallet"}
    assert str(keyed["assets.bank"].parent_id) == ids["Assets"] and keyed["assets.bank"].name == "Bank Account"
    assert by_name["HDFC"].parent_id == keyed["assets.bank"].id
    assert by_name["Amex"].parent_id == keyed["liabilities.cards"].id
    assert str(by_name["Due from Asha"].parent_id) == ids["Assets"]
    assert "parent_id" in {c["name"] for c in sa.inspect(engine).get_columns("budget_categories")}
    command.upgrade(config, AFTER)  # and up again
    assert _version(engine) == AFTER
