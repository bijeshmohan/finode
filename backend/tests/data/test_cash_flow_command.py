"""The command a person's books are converted with (`python -m finode.commands.cash_flow`): a dry run by default, and
the real run only with a backup on disk and nothing left undecided."""

from datetime import date

from sqlmodel import Session

from finode.commands.cash_flow import main
from finode.schemas.category import CategoryCreate
from tests.conftest import TEST_USER_ID
from tests.data.test_cash_flow_conversion import _build, _entry, _line


def _setup(session, monkeypatch):
    s, ids = _build(session)
    engine = session.get_bind()
    return s, ids, lambda: Session(engine)


def _names(session):
    from tests.svc import services

    session.expire_all()
    session.info.pop("read_memory", None)  # what this session read before the command changed the books
    return {a.name for a in services(session).accounts.ar.list()}


def test_dry_run_prints_every_section_and_changes_nothing(session, monkeypatch, capsys):
    _, _, factory = _setup(session, monkeypatch)
    assert main(["--user", str(TEST_USER_ID)], factory) == 0
    out = capsys.readouterr().out
    for heading in ("Retired", "Moved", "Rewritten", "Deleted", "New categories", "Needs a decision"):
        assert heading in out
    assert "Liabilities:Loans:Home Loan → deleted" in out
    assert "Home Loan" in _names(session)


def test_apply_needs_a_backup(session, monkeypatch, tmp_path, capsys):
    _, _, factory = _setup(session, monkeypatch)
    assert main(["--user", str(TEST_USER_ID), "--apply"], factory) == 2
    assert main(["--user", str(TEST_USER_ID), "--apply", "--backup", str(tmp_path / "missing.sql.gz")], factory) == 2
    empty = tmp_path / "empty.sql.gz"
    empty.write_bytes(b"")
    assert main(["--user", str(TEST_USER_ID), "--apply", "--backup", str(empty)], factory) == 2
    assert "Home Loan" in _names(session)


def test_apply_refuses_while_something_needs_a_decision(session, monkeypatch, tmp_path, capsys):
    s, ids, factory = _setup(session, monkeypatch)
    refunds = s.categories.create(CategoryCreate(name="Refunds", kind="spending"))
    _entry(  # a loan payment with a refund line: the rewrite would put Expenses on both sides
        s,
        date(2026, 11, 3),
        "Odd",
        _line(ids.loan, "debit", "1000"),
        _line(None, "credit", "200", refunds.id),
        _line(ids.hdfc, "credit", "800"),
    )
    backup = tmp_path / "finode.sql.gz"
    backup.write_bytes(b"dump")
    assert main(["--user", str(TEST_USER_ID), "--apply", "--backup", str(backup)], factory) == 3
    assert "Home Loan" in _names(session)


def test_apply_converts(session, monkeypatch, tmp_path, capsys):
    _, _, factory = _setup(session, monkeypatch)
    backup = tmp_path / "finode.sql.gz"
    backup.write_bytes(b"dump")
    assert main(["--user", str(TEST_USER_ID), "--apply", "--backup", str(backup)], factory) == 0
    assert "Categories made" in capsys.readouterr().out
    names = _names(session)
    assert "Home Loan" not in names and "Prepaid Wallet" in names


def test_retire_and_as_name_accounts_by_path(session, monkeypatch, tmp_path, capsys):
    _, _, factory = _setup(session, monkeypatch)
    backup = tmp_path / "finode.sql.gz"
    backup.write_bytes(b"dump")
    argv = [
        "--user",
        str(TEST_USER_ID),
        "--retire",
        "Assets:Bank Accounts:Old SBI",
        "--as",
        "Assets:Wallets=Prepaid Wallet",
    ]
    assert main([*argv, "--apply", "--backup", str(backup)], factory) == 0
    names = _names(session)
    assert "Old SBI" not in names and "Paytm" in names


def test_an_unknown_path_or_type_changes_nothing(session, monkeypatch, capsys):
    _, _, factory = _setup(session, monkeypatch)
    assert main(["--user", str(TEST_USER_ID), "--retire", "Assets:Nowhere"], factory) == 4
    assert main(["--user", str(TEST_USER_ID), "--as", "Assets:Wallets=Savings"], factory) == 4
    assert "Home Loan" in _names(session)
