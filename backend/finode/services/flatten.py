"""Flattening the categories of an older file (a backup or a ledger journal from when a category could hold others).

Every subcategory becomes a category of its own. A group with nothing of its own (no lines, budget rows, recurring
rules or rows, shared expenses: `has_own`) goes; one with something of its own stays as a category. When two names
now clash within a kind, each clashing subcategory takes its old group's name in front ("Household Maintenance"), cut
to the 40 characters a name may have, and a number after that if the name is still taken ("Household Maintenance 2").
A top-level category always keeps its name."""

from collections.abc import Sequence
from uuid import UUID

NAME_LIMIT = 40

# (id, name, kind, parent id) of a category as an older file has it.
OldCategory = tuple[UUID, str, str, UUID | None]


def _numbered(base: str, kind: str, taken: set[tuple[str, str]]) -> str:
    name, n = base[:NAME_LIMIT], 1
    while (kind, name.casefold()) in taken:
        n += 1
        suffix = f" {n}"
        name = base[: NAME_LIMIT - len(suffix)] + suffix
    return name


def flat_category_names(categories: Sequence[OldCategory], has_own: set[UUID]) -> tuple[dict[UUID, str], set[UUID]]:
    """The name of every category that is kept, by id, and the ids of the groups that go."""
    by_id = {c[0]: c for c in categories}
    parent_of = {c[0]: c[3] for c in categories if c[3] is not None and c[3] in by_id}
    groups = set(parent_of.values())
    dropped = {g for g in groups if g not in has_own}
    tops = [c for c in categories if c[0] not in parent_of and c[0] not in dropped]
    subs = [c for c in categories if c[0] in parent_of]

    counts: dict[tuple[str, str], int] = {}
    for _, name, kind, _ in [*tops, *subs]:
        counts[(kind, name.casefold())] = counts.get((kind, name.casefold()), 0) + 1

    names: dict[UUID, str] = {}
    taken: set[tuple[str, str]] = set()
    for category_id, name, kind, _ in tops:
        names[category_id] = name
        taken.add((kind, name.casefold()))
    plain = [c for c in subs if counts[(c[2], c[1].casefold())] == 1]
    clashing = [c for c in subs if counts[(c[2], c[1].casefold())] > 1]
    for category_id, name, kind, _ in plain:
        names[category_id] = name
        taken.add((kind, name.casefold()))
    for category_id, name, kind, parent in clashing:
        group = by_id[parent][1] if parent is not None else ""
        names[category_id] = _numbered(f"{group} {name}", kind, taken)
        taken.add((kind, names[category_id].casefold()))
    return names, dropped
