"""Tags become their own thing on an entry, no longer #words in the note

Revision ID: a2c4e6f8b1d3
Revises: e5a7c9b1d3f4
Create Date: 2026-10-26 09:00:00.000000

Two new tables: `tags` (a person's tag, lower case, unique per person) and `transaction_tags` (which entries carry
which tag). The tags already written in notes (#goa-trip) are moved: each becomes a real tag on its entry and is taken
out of the note (a note left empty becomes NULL). A tag that does not fit the rules (longer than 30 characters) or
that would be an entry's eleventh stays in the note as plain text. A tag that is part of the sentence (right after
a word such as "through" or "with": "paid through #UPI") keeps its word in the note, without the #.

Downgrading puts each entry's tags back on the end of its note (" #a #b", the note trimmed to fit 200 characters) and
drops the tables.
"""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2c4e6f8b1d3"
down_revision: str | Sequence[str] | None = "e5a7c9b1d3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A frozen copy of the rules app/tags.py had when this was written (the migration must not change with the app).
MAX_TAG = 30
MAX_PER_ENTRY = 10
_TAG = re.compile(rf"(?<!\S)#([A-Za-z0-9](?:[A-Za-z0-9_-]{{0,{MAX_TAG - 2}}}[A-Za-z0-9])?)(?![A-Za-z0-9])")


# A tag right after one of these words is part of the sentence ("paid through #UPI"): the word stays in the note
# without its # and the tag is made as well.
_CONNECTORS = frozenset(
    [
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "per",
        "the",
        "through",
        "to",
        "using",
        "via",
        "with",
    ]
)


def _split(note: str) -> tuple[str, list[str]]:
    """(the note without its tags, the tags in the order they appear, lower case, each once, at most 10)."""
    names: list[str] = []
    kept = note
    matches = [m for m in _TAG.finditer(note) if any(c.isalpha() for c in m.group(1))]
    for match in reversed(matches):
        before = note[: match.start()].split()
        if before and before[-1].lower() in _CONNECTORS:
            kept = kept[: match.start()] + match.group(1) + kept[match.end() :]  # a word of the sentence: keep it
        else:
            kept = kept[: match.start()] + kept[match.end() :]
    for match in matches:
        name = match.group(1).lower()
        if name not in names:
            names.append(name)
    if len(names) > MAX_PER_ENTRY:
        return note, []  # too many: leave this note exactly as it is
    return " ".join(kept.split()), names


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tgid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("tgid"),
        sa.UniqueConstraint("user", "name", name="uq_tags_user_name"),
    )
    op.create_index(op.f("ix_tags_user"), "tags", ["user"], unique=False)
    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.tid"]),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.tgid"]),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("transaction_id", "tag_id"),
    )
    op.create_index(op.f("ix_transaction_tags_user"), "transaction_tags", ["user"], unique=False)
    op.create_index("ix_transaction_tags_user_tag", "transaction_tags", ["user", "tag_id"], unique=False)
    _move_tags_out_of_notes()


def _move_tags_out_of_notes() -> None:
    bind = op.get_bind()
    transactions = sa.table(
        "transactions", sa.column("tid", sa.Uuid()), sa.column("user", sa.Uuid()), sa.column("comment", sa.String())
    )
    tags = sa.table(
        "tags",
        sa.column("created", sa.DateTime(timezone=True)),
        sa.column("updated", sa.DateTime(timezone=True)),
        sa.column("tgid", sa.Uuid()),
        sa.column("user", sa.Uuid()),
        sa.column("name", sa.String()),
    )
    links = sa.table(
        "transaction_tags",
        sa.column("transaction_id", sa.Uuid()),
        sa.column("tag_id", sa.Uuid()),
        sa.column("user", sa.Uuid()),
    )
    now = datetime.now(UTC)
    made: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
    rows = bind.execute(
        sa.select(transactions.c.tid, transactions.c.user, transactions.c.comment).where(
            transactions.c.comment.like("%#%")
        )
    ).all()
    for tid, user, note in rows:
        words, names = _split(note or "")
        if not names:
            continue
        for name in names:
            if (user, name) not in made:
                made[(user, name)] = uuid.uuid4()
                bind.execute(
                    sa.insert(tags).values(created=now, updated=now, tgid=made[(user, name)], user=user, name=name)
                )
            bind.execute(sa.insert(links).values(transaction_id=tid, tag_id=made[(user, name)], user=user))
        bind.execute(sa.update(transactions).where(transactions.c.tid == tid).values(comment=words or None))


def downgrade() -> None:
    bind = op.get_bind()
    transactions = sa.table("transactions", sa.column("tid", sa.Uuid()), sa.column("comment", sa.String()))
    tags = sa.table("tags", sa.column("tgid", sa.Uuid()), sa.column("name", sa.String()))
    links = sa.table("transaction_tags", sa.column("transaction_id", sa.Uuid()), sa.column("tag_id", sa.Uuid()))
    rows = bind.execute(
        sa.select(links.c.transaction_id, tags.c.name).join(tags, tags.c.tgid == links.c.tag_id).order_by(tags.c.name)
    ).all()
    per_entry: dict[uuid.UUID, list[str]] = {}
    for tid, name in rows:
        per_entry.setdefault(tid, []).append(name)
    for tid, names in per_entry.items():
        note = bind.execute(sa.select(transactions.c.comment).where(transactions.c.tid == tid)).scalar() or ""
        suffix = " ".join(f"#{name}" for name in names)
        room = max(0, 200 - len(suffix) - 1)
        words = note[:room].rstrip()
        bind.execute(
            sa.update(transactions).where(transactions.c.tid == tid).values(comment=f"{words} {suffix}".strip()[:200])
        )
    op.drop_index("ix_transaction_tags_user_tag", table_name="transaction_tags")
    op.drop_index(op.f("ix_transaction_tags_user"), table_name="transaction_tags")
    op.drop_table("transaction_tags")
    op.drop_index(op.f("ix_tags_user"), table_name="tags")
    op.drop_table("tags")
