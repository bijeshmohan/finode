"""The session remembers what it read (repositories/cache.py) and must never show what was true before a write."""

from uuid import uuid4

from sqlalchemy import event, text

from app.models.account import Account
from app.repositories import AccountRepository, ProfileRepository
from app.schemas import AccountCreate

from .conftest import TEST_USER_ID
from .svc import services


def count(session):
    n = {"queries": 0}
    event.listen(
        session.get_bind(), "before_cursor_execute", lambda *a, **k: n.__setitem__("queries", n["queries"] + 1)
    )
    return n


def test_a_second_read_in_the_same_session_does_not_ask_the_database(session):
    repo = AccountRepository(session, TEST_USER_ID)
    services(session).accounts.list()  # creates the roots
    n = count(session)
    first = repo.list()
    after_first = n["queries"]
    second = repo.list()
    assert n["queries"] == after_first, "the second read went to the database"
    assert [a.aid for a in first] == [a.aid for a in second]
    assert first is not second, "callers get their own list"


def test_an_account_created_after_a_read_shows_up_in_the_next_one(session):
    s = services(session)
    root = next(a for a in s.accounts.list() if a.name == "Assets")
    before = {a.name for a in AccountRepository(session, TEST_USER_ID).list()}
    s.accounts.create(AccountCreate(name="Fresh", parent_id=root.aid))
    after = {a.name for a in AccountRepository(session, TEST_USER_ID).list()}
    assert "Fresh" not in before and "Fresh" in after


def test_an_object_added_but_not_yet_written_is_still_seen(session):
    repo = AccountRepository(session, TEST_USER_ID)
    services(session).accounts.list()
    repo.list()
    root = next(a for a in repo.list() if a.name == "Expenses")
    session.add(Account(name="Pending", parent_id=root.aid, user=TEST_USER_ID))  # not flushed yet
    assert "Pending" in {a.name for a in repo.list()}


def test_a_plain_sql_update_makes_the_session_forget(session):
    s = services(session)
    s.accounts.list()
    profile = ProfileRepository(session, TEST_USER_ID)
    assert profile.get_or_create().currency == "INR"
    assert profile.read().currency == "INR"
    session.execute(text("UPDATE profiles SET currency = 'USD'"))
    assert profile.read().currency == "USD"


def test_a_rollback_makes_the_session_forget(session):
    s = services(session)
    s.accounts.list()
    repo = AccountRepository(session, TEST_USER_ID)
    root = next(a for a in repo.list() if a.name == "Assets")
    session.add(Account(name="Doomed", parent_id=root.aid, user=TEST_USER_ID))
    session.flush()
    assert "Doomed" in {a.name for a in repo.list()}
    session.rollback()
    assert "Doomed" not in {a.name for a in repo.list()}


def test_one_person_never_sees_anothers_remembered_rows(session):
    other = uuid4()
    mine = services(session)
    mine.accounts.list()
    theirs = AccountRepository(session, other)
    assert theirs.list() == [] and len(AccountRepository(session, TEST_USER_ID).list()) == 5
