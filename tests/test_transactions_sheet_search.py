"""Searching and filtering the transactions list, the details sheet that opens from a row, and "add again"."""

import re
from datetime import date, timedelta

import pytest


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        response = client.post("/api/accounts/", json={"name": name, "parent_id": root_accounts[root], **extra})
        assert response.status_code == 201, response.text
        return response.json()

    return {
        "hdfc": make("HDFC", "Assets", balance="10000"),
        "cash": make("Cash", "Assets"),
        "card": make("Regalia Gold", "Liabilities"),
        "delivery": make("Delivery", "Expenses"),
        "groceries": make("Groceries", "Expenses"),
        "salary": make("Salary", "Income"),
    }


def post(client, payee, debit, credit, amount="10", **extra):
    response = client.post("/api/transactions/", json={"payee": payee, "postings": [
        {"account": debit["aid"], "side": "debit", "amount": amount},
        {"account": credit["aid"], "side": "credit", "amount": amount}], **extra})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def ledger(client, books):
    return {
        "swiggy": post(client, "Swiggy", books["delivery"], books["card"], "597"),
        "dmart": post(client, "DMart", books["groceries"], books["hdfc"], "1286", comment="weekly shop"),
        "pay": post(client, "Employer", books["hdfc"], books["salary"], "5000"),
        "move": post(client, "Card payment", books["card"], books["hdfc"], "300"),
    }


def titles(html):
    return re.findall(r'<span class="tx-title">([^<]*)</span>', html)


def page(client, **params):
    response = client.get("/transactions", params=params)
    assert response.status_code == 200, response.text
    return response.text


# ---- search ---------------------------------------------------------------------------------------------------


def test_search_finds_a_payee_a_note_or_an_account(client, books, ledger):
    assert titles(page(client, q="swig")) == ["Swiggy"], "part of a name, in any case"
    assert titles(page(client, q="WEEKLY")) == ["DMart"], "the note"
    assert set(titles(page(client, q="groceries"))) == {"DMart"}, "the name of an account used"
    assert set(titles(page(client, q="regalia"))) == {"Swiggy", "Card payment"}


def test_search_that_finds_nothing_says_so(client, books, ledger):
    html = page(client, q="zzz")
    assert titles(html) == [] and "Nothing matches." in html and "Show everything" in html


def test_search_treats_percent_and_underscore_as_plain_text(client, books, ledger):
    post(client, "100% juice", books["groceries"], books["cash"])
    assert titles(page(client, q="%")) == ["100% juice"]
    assert titles(page(client, q="_")) == []


def test_search_box_keeps_what_was_typed(client, books, ledger):
    assert 'name="q" value="swig"' in page(client, q="swig")


# ---- the kind chips --------------------------------------------------------------------------------------------


def test_chips_filter_by_what_kind_of_entry_it_is(client, books, ledger):
    assert set(titles(page(client, kind="expense"))) == {"Swiggy", "DMart"}
    assert titles(page(client, kind="income")) == ["Employer"]
    assert set(titles(page(client, kind="transfer"))) == {"Card payment", "Opening balance"}
    assert len(titles(page(client))) == 5, "All shows everything"
    assert len(titles(page(client, kind="nonsense"))) == 5, "an unknown chip is ignored"


def test_the_chosen_chip_is_marked_and_chips_keep_the_search(client, books, ledger):
    html = page(client, kind="expense", q="swig")
    chips = {href.replace("&amp;", "&"): state for href, state in re.findall(r'<a class="chip" href="([^"]*)" aria-pressed="(\w+)">', html)}
    month = date.today().strftime("%Y-%m")
    assert [k for k, v in chips.items() if v == "true"] == [f"/transactions?month={month}&q=swig"], "the chosen chip clears itself and keeps the search"
    assert f"/transactions?month={month}&q=swig&kind=income" in chips
    plain = [h.replace("&amp;", "&") for h in re.findall(r'<a class="chip" href="([^"]*)"', page(client))]
    assert plain == [f"/transactions?month={month}&kind={k}" for k in ("expense", "income", "transfer")]


def test_search_and_kind_combine_and_page(client, books, ledger):
    assert titles(page(client, kind="expense", q="swig")) == ["Swiggy"]
    assert titles(page(client, kind="income", q="swig")) == []


# ---- the details sheet ----------------------------------------------------------------------------------------


def sheet(client, tx):
    response = client.get(f"/transactions/{tx['tid']}/sheet")
    assert response.status_code == 200, response.text
    return response.text


def flat(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_the_sheet_shows_the_entry(client, books, ledger):
    text = flat(sheet(client, ledger["swiggy"]))
    assert "Swiggy" in text and "597.00" in text and "−597.00" not in text, "an ordinary expense has no minus"
    assert "Paid from Regalia Gold" in text and "Spent on Delivery" in text
    assert "Note None" in text and "Added By the API" in text


def test_the_labels_follow_the_kind(client, books, ledger):
    assert "From Salary Received in HDFC" in flat(sheet(client, ledger["pay"]))
    assert "+5,000.00" in flat(sheet(client, ledger["pay"]))
    move = flat(sheet(client, ledger["move"]))
    assert "From HDFC To Regalia Gold" in move


def test_the_note_is_shown_and_escaped(client, books):
    tx = post(client, "Shop", books["groceries"], books["cash"], comment="<b>hi</b>")
    html = sheet(client, tx)
    assert "<b>hi</b>" not in html and "&lt;b&gt;hi" in html


def test_a_split_lists_every_account_with_its_amount(client, books):
    tx = client.post("/api/transactions/", json={"payee": "Big shop", "postings": [
        {"account": books["groceries"]["aid"], "side": "debit", "amount": "600"},
        {"account": books["delivery"]["aid"], "side": "debit", "amount": "300"},
        {"account": books["hdfc"]["aid"], "side": "credit", "amount": "900"}]}).json()
    text = flat(sheet(client, tx))
    assert "Groceries 600.00" in text and "Delivery 300.00" in text and "900.00" in text and "−900.00" not in text


def test_the_sheet_offers_edit_add_again_and_delete(client, books, ledger):
    html = sheet(client, ledger["dmart"])
    assert f'href="/transactions/{ledger["dmart"]["tid"]}/edit"' in html
    assert f'href="/transactions/new?repeat={ledger["dmart"]["tid"]}"' in html
    assert f'hx-post="/transactions/{ledger["dmart"]["tid"]}/delete"' in html and "hx-confirm" not in html, "undo replaces the confirmation"


def test_an_entry_in_a_locked_period_cannot_be_changed_from_the_sheet(client, books):
    old = post(client, "Old", books["groceries"], books["cash"], date=(date.today() - timedelta(days=40)).isoformat())
    client.patch("/api/profile/", json={"locked_through": (date.today() - timedelta(days=30)).isoformat()})
    html = sheet(client, old)
    assert "locked period" in html and 'aria-disabled="true"' in html and "disabled" in html
    refused = client.post(f"/transactions/{old['tid']}/delete", data={"sheet": "1"})
    assert refused.status_code == 400 and refused.headers["HX-Retarget"] == "#sheet-error"


def test_a_missing_entry_has_no_sheet(client, books, ledger):
    assert client.get("/transactions/00000000-0000-4000-8000-0000000000aa/sheet").status_code == 404


def test_rows_open_the_sheet_and_fall_back_to_the_edit_page(client, books, ledger):
    html = page(client)
    tid = ledger["swiggy"]["tid"]
    assert f'href="/transactions/{tid}/edit" hx-get="/transactions/{tid}/sheet" hx-target="#txn-sheet-body"' in html
    assert html.count('<dialog id="txn-sheet"') == 1
    assert 'id="txn-sheet"' in client.get("/").text, "Home's recent rows open it too"


# ---- add again ------------------------------------------------------------------------------------------------


def test_add_again_copies_the_entry_for_today(client, books, ledger):
    html = client.get("/transactions/new", params={"repeat": ledger["dmart"]["tid"]}).text
    assert 'value="1286.00"' in html and 'value="DMart"' in html and 'value="weekly shop"' in html
    assert f'name="date" value="{date.today().isoformat()}"' in html
    assert f'<option value="{books["hdfc"]["aid"]}" selected' in html
    assert f'<option value="{books["groceries"]["aid"]}" selected' in html
    assert 'name="kind" value="expense"' in html


def test_add_again_keeps_every_row_of_a_split(client, books):
    tx = client.post("/api/transactions/", json={"payee": "Big shop", "postings": [
        {"account": books["groceries"]["aid"], "side": "debit", "amount": "600"},
        {"account": books["delivery"]["aid"], "side": "debit", "amount": "300"},
        {"account": books["hdfc"]["aid"], "side": "credit", "amount": "900"}]}).json()
    html = client.get("/transactions/new", params={"repeat": tx["tid"]}).text
    assert html.count('name="side" value="debit"') >= 2 and 'value="600.00"' in html and 'value="300.00"' in html and 'value="900.00"' in html


def test_add_again_of_a_missing_entry(client, books):
    assert client.get("/transactions/new", params={"repeat": "00000000-0000-4000-8000-0000000000aa"}).status_code == 404


def test_the_older_chip_spellings_still_work_and_show_the_new_chip(client, books):
    assert set(titles(page(client, kind="spending"))) == set(titles(page(client, kind="expense")))
    assert set(titles(page(client, kind="transfers"))) == set(titles(page(client, kind="transfer")))
    html = page(client, kind="spending")
    assert ">Expense<" in html and ">Transfer<" in html and ">Spending<" not in html and ">Transfers<" not in html
