"""The Advanced switch: off hides the rarely used features (never the data), on shows them again."""

import pytest


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        response = client.post("/api/accounts/", json={"name": name, "parent_id": root_accounts[root], **extra})
        assert response.status_code == 201, response.text
        return response.json()

    bank, food = make("Bank", "Assets", balance="1000"), make("Food", "Expenses")
    client.put(f"/api/budget/categories/{food['aid']}/target", json={"kind": "monthly", "amount": "300"})
    return {"bank": bank, "food": food}


def switch(client, on):
    response = client.post("/settings/advanced", data={"advanced": "1" if on else "0"})
    assert response.status_code == 200, response.text
    return response


def test_new_people_start_with_it_off(session):
    from uuid import uuid4

    from app.repositories import profile as repository

    repository.NEW_PROFILE_ADVANCED = False  # what production does; the test fixture turns it on for the others
    try:
        assert repository.ProfileRepository(session, uuid4()).get_or_create().advanced is False
    finally:
        repository.NEW_PROFILE_ADVANCED = True


def test_the_switch_saves_and_shows_in_settings(client):
    assert client.get("/api/profile/").json()["advanced"] is True
    assert "advanced-off" in switch(client, False).headers["set-cookie"]
    assert client.get("/api/profile/").json()["advanced"] is False
    assert 'id="advanced"' in (page := client.get("/settings").text) and ">Off<" in page
    switch(client, True)
    assert ">On<" in client.get("/settings").text


def test_off_hides_the_lock_but_explains_it(client):
    switch(client, False)
    page = client.get("/settings/advanced").text
    assert 'aria-checked="false"' in page and 'id="lock"' not in page
    assert "Period lock" in page, "listed, dimmed, so people know it exists"
    switch(client, True)
    page = client.get("/settings/advanced").text
    assert 'aria-checked="true"' in page and 'id="lock"' in page


def test_off_hides_targets_on_the_budget_and_keeps_the_money(client, books):
    food = books["food"]["aid"]
    on = client.get("/budget").text
    assert "needs 300.00 more" in on and "Assign what is needed" in on
    assert "Monthly 300.00" in client.get(f"/budget/category/{food}/sheet").text
    switch(client, False)
    off = client.get("/budget").text
    assert "needs 300.00 more" not in off and "Assign what is needed" not in off
    sheet = client.get(f"/budget/category/{food}/sheet").text
    assert "Monthly 300.00" not in sheet and "Target and note" not in sheet and f'aria-label="Assigned to Food"' in sheet, "assigning stays"
    assert client.get("/api/budget/").json()["underfunded"] == "300.00", "the data is untouched"


def test_off_hides_order_and_close_on_an_account(client, books):
    aid = books["bank"]["aid"]
    on = client.get(f"/accounts/{aid}").text
    assert "Close account" in on
    switch(client, False)
    off = client.get(f"/accounts/{aid}").text
    assert "Close account" not in off and "listed alphabetically" not in off
    assert "Edit" in off and "New transaction" in off


def test_a_deleted_category_can_still_be_restored_with_the_switch_off(client, books):
    aid = books["food"]["aid"]
    assert client.post(f"/api/accounts/{aid}/close").status_code == 200
    switch(client, False)
    assert "Restore category" in client.get(f"/accounts/{aid}").text


def test_the_switch_is_in_the_backup(client):
    switch(client, False)
    backup = client.get("/api/backup").json()
    assert backup["profile"]["advanced"] is False


def test_an_account_page_has_no_empty_menu_when_there_is_nothing_in_it(client, books):
    """An account with entries cannot get sub-accounts, and Advanced is off: the '...' button would open an empty box."""
    client.post("/api/transactions/", json={"postings": [
        {"account": books["food"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["bank"]["aid"], "side": "credit", "amount": "5"}]})
    switch(client, False)
    page = client.get(f"/accounts/{books['bank']['aid']}").text
    assert 'class="menu"' not in page and "Edit Bank" in page, "the pencil stays, the empty menu goes"
    switch(client, True)
    assert 'class="menu"' in client.get(f"/accounts/{books['bank']['aid']}").text, "Advanced adds Close account"
    switch(client, False)
    assert 'class="menu"' in client.get(f"/categories/{books['food']['aid']}").text, "a category always has Delete"
