"""The built-in groups on the web: Accounts page headings with a round +, the form starting as the group says, no menu."""

import pytest

from app.services import account as account_service

from .test_fixed_parents import group, make


@pytest.fixture(autouse=True)
def new_person(monkeypatch):
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)


def test_the_form_offers_the_five_kinds_in_the_pages_order_and_starts_on_none(client):
    blank = client.get("/api/views/account-form").json()
    assert [k["name"] for k in blank["kinds"]] == ["Bank Accounts", "Cash", "Credit Cards", "Investments", "Loans"]
    assert blank["parent_id"] is None, "nothing is chosen for the person"
    loans = group(client, "Loans")["id"]
    assert client.get("/api/views/account-form", params={"parent": loans}).json()["parent_id"] == loans


def test_the_form_starts_as_the_group_says(client):
    def starts(name):
        return client.get("/api/views/account-form", params={"parent": group(client, name)["id"]}).json()["on_budget"]

    assert (starts("Investments"), starts("Bank Accounts"), starts("Loans")) == (False, True, False)


def test_the_empty_groups_are_not_offered_to_post_to(client):
    hdfc = make(client, "HDFC", "Bank Accounts")
    offered = {o["id"] for g in client.get("/api/views/entry-form").json()["groups"] for o in g["options"]}
    assert hdfc["id"] in offered
    assert group(client, "Investments")["id"] not in offered and group(client, "Loans")["id"] not in offered
