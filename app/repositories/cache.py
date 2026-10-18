"""Reads remembered for the length of one session (one web request, one tool call).

A page asks several services for the same thing (the account list, every posting, the profile, the budget targets),
each unaware of the others, and every ask is a round trip to a database about 15 ms away. `remembered` loads such a
thing once and hands the same rows to the next asker.

It is only safe because it forgets at the right moments: the memory is dropped whenever the session writes (a flush,
a commit, a rollback, any statement that is not a plain SELECT), and it is not used while the session holds changes
that are not yet written (a new, changed or deleted object), because then the query that would run is the one that
writes them first. So a read can never return what was true before a write made in the same session.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy import event
from sqlmodel import Session


def _forget(session: Session, *_: Any) -> None:
    session.info.pop("read_memory", None)


def _forget_unless_select(state) -> None:
    if not state.is_select:
        _forget(state.session)


event.listen(Session, "after_flush", _forget)
event.listen(Session, "after_commit", _forget)
event.listen(Session, "after_rollback", _forget)
event.listen(Session, "after_soft_rollback", _forget)
event.listen(Session, "do_orm_execute", _forget_unless_select)


def remembered(db: Session, key: tuple, load: Callable[[], Any]) -> Any:
    """`load()` once per session for this key, as long as nothing was written in between.

    The result is shared: callers must not change it (lists are returned as they were loaded; copy before sorting).
    """
    if db.new or db.dirty or db.deleted:
        return load()
    memory = db.info.get("read_memory")
    if memory is not None and key in memory:
        return memory[key]
    value = load()  # may flush first (autoflush), which forgets; the answer read after that is still the current one
    if not (db.new or db.dirty or db.deleted):
        db.info.setdefault("read_memory", {})[key] = value
    return value
