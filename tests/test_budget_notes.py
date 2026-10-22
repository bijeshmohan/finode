"""A short note on a budget category (kept as the account's details)."""

import pytest

from .test_budget import account, budget, line  # noqa: F401


@pytest.fixture
def setup(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="1000")
    rent = account(client, root_accounts, "Rent", "Expenses")
    food = account(client, root_accounts, "Food", "Expenses")
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": food["aid"]}).json()
    return {"bank": bank, "rent": rent, "food": food, "groceries": groceries}


class Saved:
    """What saving a note did: the status of the form's answer, and the budget as it reads afterwards."""

    def __init__(self, client, response):
        self.client, self.status_code, self.headers, self.text = client, response.status_code, response.headers, response.text

    def json(self):
        return budget(self.client)


def put_note(client, category, note):
    """Save a note the way the category's page does."""
    return Saved(client, client.post("/plan/note", data={"category": category["aid"], "note": note or ""}))


def test_a_note_shows_on_the_category(client, setup):
    assert line(budget(client), "Rent")["note"] is None
    response = put_note(client, setup["rent"], "  Due on the 5th, pay by UPI  ")
    assert response.status_code == 200
    assert line(response.json(), "Rent")["note"] == "Due on the 5th, pay by UPI"
    assert line(budget(client), "Food")["note"] is None, "other categories are untouched"


def test_it_is_the_accounts_details(client, setup):
    put_note(client, setup["rent"], "Landlord: Mr Rao")
    assert client.get(f"/api/accounts/{setup['rent']['aid']}").json()["details"] == "Landlord: Mr Rao"
    client.patch(f"/api/accounts/{setup['rent']['aid']}", json={"details": "Edited on the account"})
    assert line(budget(client), "Rent")["note"] == "Edited on the account"


def test_an_empty_note_removes_it(client, setup):
    put_note(client, setup["rent"], "x")
    for empty in ("", "   ", None):
        put_note(client, setup["rent"], "again")
        data = put_note(client, setup["rent"], empty).json()
        assert line(data, "Rent")["note"] is None
    assert client.get(f"/api/accounts/{setup['rent']['aid']}").json()["details"] is None


def test_a_group_has_its_note_but_not_on_its_other_row(client, setup):
    client.post("/api/transactions/", json={"postings": [
        {"account": setup["food"]["aid"], "side": "debit", "amount": "5"},
        {"account": setup["bank"]["aid"], "side": "credit", "amount": "5"}]})  # posted to the group itself: an (other) row
    data = put_note(client, setup["food"], "Weekly shop on Saturdays").json()
    assert line(data, "Food")["note"] == "Weekly shop on Saturdays" and line(data, "Food")["group"] is True
    assert line(data, "Food (other)")["note"] is None


def test_validation(client, setup):
    assert put_note(client, setup["rent"], "x" * 201).status_code == 400
    assert put_note(client, setup["bank"], "not a category").status_code == 400
    assert put_note(client, {"aid": "00000000-0000-4000-8000-0000000000aa"}, "x").status_code == 400


def test_the_page_shows_the_note_and_the_form_saves_it(client, setup):
    rent = setup["rent"]["aid"]
    form = client.get(f"/plan/target?category={rent}").text
    assert 'hx-post="/plan/note"' in form and "<textarea" in form
    saved = client.post("/plan/note", data={"category": rent, "note": "Due on the 5th"})
    assert saved.status_code == 200 and saved.headers["HX-Redirect"].startswith("/plan?month=")
    assert "budget-note" in saved.headers["set-cookie"]
    assert "Due on the 5th" in client.get("/plan").text, "the note is the row's caption"
    assert "Due on the 5th" in client.get(f"/plan/category/{rent}/sheet").text
    assert "Due on the 5th</textarea>" in client.get(f"/plan/target?category={rent}").text


def test_the_form_reports_problems_in_place(client, setup):
    bad = client.post("/plan/note", data={"category": setup["rent"]["aid"], "note": "x" * 300})
    assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#note-error" and "at most 200" in bad.text
    bad = client.post("/plan/note", data={"category": setup["bank"]["aid"], "note": "x"})
    assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#note-error"


def test_notes_are_escaped(client, setup):
    put_note(client, setup["rent"], "<script>alert(1)</script>")
    page = client.get("/plan").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
