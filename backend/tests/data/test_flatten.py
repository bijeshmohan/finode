"""Flattening categories from an older file (services/flatten.py): every subcategory becomes a category, a group with
nothing of its own goes, one with something of its own stays, and a clashing name takes its old group's name."""

from uuid import uuid4

from finode.services.flatten import flat_category_names


def _cat(name, kind="spending", parent=None):
    return (uuid4(), name, kind, parent)


def test_subcategories_become_categories():
    food = _cat("Food")
    dairy, meat = _cat("Dairy", parent=food[0]), _cat("Meat", parent=food[0])
    names, dropped = flat_category_names([food, dairy, meat], has_own=set())
    assert names == {dairy[0]: "Dairy", meat[0]: "Meat"} and dropped == {food[0]}


def test_a_group_with_nothing_of_its_own_goes():
    travel = _cat("Travel")
    stay = _cat("Stay", parent=travel[0])
    names, dropped = flat_category_names([travel, stay], has_own=set())
    assert travel[0] in dropped and travel[0] not in names


def test_a_group_with_its_own_lines_stays():
    groceries = _cat("Groceries")
    dairy = _cat("Dairy", parent=groceries[0])
    names, dropped = flat_category_names([groceries, dairy], has_own={groceries[0]})
    assert names == {groceries[0]: "Groceries", dairy[0]: "Dairy"} and dropped == set()


def test_a_lone_category_stays_whatever_it_holds():
    rent = _cat("Rent")
    names, dropped = flat_category_names([rent], has_own=set())
    assert names == {rent[0]: "Rent"} and dropped == set()


def test_clashing_names_take_their_group():
    household, transport = _cat("Household"), _cat("Transportation")
    a = _cat("Maintenance", parent=household[0])
    b = _cat("maintenance", parent=transport[0])
    lone = _cat("Maintenance")
    salary = _cat("Maintenance", kind="earning")
    names, _ = flat_category_names([household, transport, a, b, lone, salary], has_own=set())
    assert names[lone[0]] == "Maintenance", "a top-level category keeps its name"
    assert names[a[0]] == "Household Maintenance" and names[b[0]] == "Transportation maintenance"
    assert names[salary[0]] == "Maintenance", "another kind is no clash"


def test_a_long_name_is_cut():
    group = _cat("G" * 35)
    a, b = _cat("Subcategory", parent=group[0]), _cat("Subcategory", parent=_cat("Other")[0])
    names, _ = flat_category_names([group, a, b], has_own=set())
    assert names[a[0]] == ("G" * 35 + " Subcategory")[:40]


def test_a_taken_name_is_numbered():
    household, transport = _cat("Household"), _cat("Transportation")
    taken = _cat("Household Maintenance")
    a = _cat("Maintenance", parent=household[0])
    b = _cat("Maintenance", parent=transport[0])
    names, _ = flat_category_names([household, transport, taken, a, b], has_own=set())
    assert names[taken[0]] == "Household Maintenance" and names[a[0]] == "Household Maintenance 2"
