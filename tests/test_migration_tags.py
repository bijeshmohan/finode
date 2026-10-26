"""The migration that makes tags their own thing: the #words in notes become tags and leave the note, and it can be undone."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

BEFORE = "e5a7c9b1d3f4"
AFTER = "a2c4e6f8b1d3"
NOW = datetime.now(UTC)


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def insert(engine, user, note):
    tid = uuid4()
    with engine.begin() as c:
        c.execute(
            sa.text(
                'INSERT INTO transactions (created, updated, tid, "user", date, comment) '
                "VALUES (:created, :updated, :tid, :user, :date, :comment)"
            ).bindparams(
                sa.bindparam("created", NOW, type_=sa.DateTime(timezone=True)),
                sa.bindparam("updated", NOW, type_=sa.DateTime(timezone=True)),
                sa.bindparam("tid", tid, type_=sa.Uuid()),
                sa.bindparam("user", user, type_=sa.Uuid()),
                sa.bindparam("date", "2026-10-10"),
                sa.bindparam("comment", note),
            )
        )
    return tid


def notes(engine):
    with engine.connect() as c:
        return dict(
            c.execute(
                sa.text("SELECT tid, comment FROM transactions").columns(tid=sa.Uuid(), comment=sa.String())
            ).all()
        )


def tags_of(engine):
    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                'SELECT t.tid, g.name, g."user" FROM transactions t JOIN transaction_tags l ON l.transaction_id = t.tid '
                "JOIN tags g ON g.tgid = l.tag_id ORDER BY g.name"
            ).columns(tid=sa.Uuid(), name=sa.String(), user=sa.Uuid())
        ).all()
    found: dict = {}
    for tid, name, _user in rows:
        found.setdefault(tid, []).append(name)
    return found


def test_tags_leave_the_notes_and_become_tags(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    ana, ben = uuid4(), uuid4()
    both = insert(engine, ana, "Dinner with Ravi #Goa-Trip #reimbursable")
    only = insert(engine, ana, "#goa-trip")
    plain = insert(engine, ana, "no tags here")
    number = insert(engine, ana, "Issue #1 stays")
    nothing = insert(engine, ana, None)
    theirs = insert(engine, ben, "Lunch #goa-trip")
    twice = insert(engine, ana, "twice #emi #EMI")
    sentence = insert(engine, ana, "Ride, paid directly to driver through #UPI")
    too_many = insert(engine, ana, " ".join(f"#t{n}" for n in range(11)))
    long_one = insert(engine, ana, "#" + "a" * 31)
    command.upgrade(config, AFTER)
    after = notes(engine)
    assert after[both] == "Dinner with Ravi"
    assert after[only] is None, "a note left empty is NULL"
    assert after[plain] == "no tags here" and after[number] == "Issue #1 stays" and after[nothing] is None
    assert after[theirs] == "Lunch" and after[twice] == "twice"
    assert after[sentence] == "Ride, paid directly to driver through UPI", (
        "a tag that is part of the sentence keeps its word"
    )
    assert after[too_many] == " ".join(f"#t{n}" for n in range(11)), "more than ten: left as text"
    assert after[long_one] == "#" + "a" * 31, "too long to be a tag: left as text"
    found = tags_of(engine)
    assert found[both] == ["goa-trip", "reimbursable"] and found[only] == ["goa-trip"] and found[twice] == ["emi"]
    assert found[theirs] == ["goa-trip"] and found[sentence] == ["upi"]
    assert plain not in found and number not in found and too_many not in found
    with engine.connect() as c:
        assert (
            c.execute(
                sa.text("SELECT count(*) FROM tags WHERE \"user\" = :u AND name = 'goa-trip'"), {"u": ana.hex}
            ).scalar()
            == 1
        )
        assert c.execute(sa.text("SELECT count(*) FROM tags WHERE name = 'goa-trip'")).scalar() == 2, "one per person"


def test_going_back_puts_the_tags_on_the_end_of_the_notes(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    user = uuid4()
    one = insert(engine, user, "Dinner #goa-trip #reimbursable")
    two = insert(engine, user, "#only")
    three = insert(engine, user, "plain")
    command.upgrade(config, AFTER)
    command.downgrade(config, BEFORE)
    after = notes(engine)
    assert after[one] == "Dinner #goa-trip #reimbursable" and after[two] == "#only" and after[three] == "plain"
    assert not {"tags", "transaction_tags"} & set(sa.inspect(engine).get_table_names())


def test_a_long_note_is_trimmed_so_the_tags_fit_when_going_back(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    user = uuid4()
    tid = insert(engine, user, "x" * 190 + " #goa-trip")
    command.upgrade(config, AFTER)
    with engine.begin() as c:  # the person wrote 200 characters of words afterwards
        c.execute(
            sa.text("UPDATE transactions SET comment = :c WHERE tid = :t").bindparams(
                sa.bindparam("t", tid, type_=sa.Uuid()), sa.bindparam("c", "y" * 200)
            )
        )
    command.downgrade(config, BEFORE)
    note = notes(engine)[tid]
    assert len(note) <= 200 and note.endswith(" #goa-trip")
