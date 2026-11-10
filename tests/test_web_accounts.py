import re
from datetime import date

from fastapi.testclient import TestClient

from .books import leg, post_account

MISSING = "00000000-0000-4000-8000-0000000000ff"


def _opening_balances(client: TestClient) -> dict:
    return next(a for a in client.get("/api/accounts/").json() if a["name"] == "Opening Balances")


def _bank(client: TestClient, root_accounts: dict[str, str], balance: str = "100.00") -> dict:
    return post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": balance}).json()


# --- accounts list ---------------------------------------------------------


def test_accounts_page_lists_accounts_by_kind(client: TestClient, root_accounts: dict[str, str], account: dict):
    response = client.get("/accounts")
    assert response.status_code == 200
    text = response.text
    assert ">Asset<" not in text and ">Liability<" not in text and "?tab=" not in text, "no chips: one page"
    assert ">Equity<" not in text and "Opening Balances" not in text, "Equity is not on the page"
    assert ">Expenses<" not in text and ">Income<" not in text, "those are on the Categories page"
    assert f'href="/accounts/{account["id"]}"' in text
    assert "checking" in text


def test_accounts_page_with_no_groups_still_offers_a_new_group(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/accounts").text
    assert 'class="add-row" href="/accounts/new-group"' in text and "New group" in text
    assert "acc-kind" not in text and 'href="/accounts/new"' not in text


def test_an_old_link_to_a_tab_still_lands_on_the_page(client: TestClient, root_accounts: dict[str, str]):
    _bank(client, root_accounts)
    for tab in ("assets", "liabilities", "equity", "nonsense"):
        page = client.get(f"/accounts?tab={tab}")
        assert page.status_code == 200 and "Opening Balances" not in page.text


# --- account page ----------------------------------------------------------


def test_account_page_shows_balance_activity_and_actions(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = _bank(client, root_accounts)
    client.post(
        "/api/transactions/",
        json={
            "date": date.today().isoformat(),
            "payee": "lunch",
            "postings": [
                leg(expense_account, "debit", "30.00"),
                leg(bank, "credit", "30.00"),
            ],
        },
    )

    text = client.get(f"/accounts/{bank['id']}").text
    assert "70.00" in text
    assert "lunch" in text and "30.00" in text and "−30.00" not in text
    assert f'class="fab" href="/transactions/new?account={bank["id"]}&amp;back=/accounts/{bank["id"]}"' in text
    assert f'href="/accounts/{bank["id"]}/edit"' in text
    # it has postings, so it cannot gain sub-accounts
    assert f"/accounts/new?parent={bank['id']}" not in text


def test_account_page_for_empty_leaf_offers_sub_account(client: TestClient, account: dict):
    text = client.get(f"/accounts/{account['id']}").text
    assert f"/accounts/new?parent={account['id']}" in text
    assert "No transactions yet." in text


def test_root_and_system_account_pages_are_read_only(client: TestClient, root_accounts: dict[str, str]):
    _bank(client, root_accounts)
    for account_id in (root_accounts["Assets"], _opening_balances(client)["id"]):
        assert f"/accounts/{account_id}/edit" not in client.get(f"/accounts/{account_id}").text
    root_page = client.get(f"/accounts/{root_accounts['Assets']}").text
    assert f"/transactions/new?account={root_accounts['Assets']}" not in root_page
    assert client.get(f"/accounts/{root_accounts['Assets']}/edit").status_code == 404


def test_account_page_not_found(client: TestClient):
    assert client.get(f"/accounts/{MISSING}").status_code == 404


# --- create ----------------------------------------------------------------


def test_new_account_page_preselects_parent(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/accounts/new", params={"parent": root_accounts["Liabilities"]}).text
    assert f'<option value="{root_accounts["Liabilities"]}" selected' in text
    assert 'name="balance"' in text
    assert f'value="{root_accounts["Income"]}"' not in text, "Income and Expenses are for categories"


def test_new_category_page_offers_income_and_expenses_and_no_balance(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/categories/new", params={"root": "income"}).text
    assert 'name="kind" value="earning"' in text and f'value="{root_accounts["Assets"]}"' not in text
    assert 'name="balance"' not in text and "Add category" in text


def test_create_account_from_form(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        "/accounts",
        data={
            "name": "wallet",
            "parent_id": root_accounts["Assets"],
            "balance": "1,250.50",
            "details": "pocket",
        },
    )
    assert response.status_code == 200
    created = next(a for a in client.get("/api/accounts/").json() if a["name"] == "wallet")
    assert response.headers["HX-Redirect"] == f"/accounts/{created['id']}"
    assert created["balance"] == "1250.50"
    assert created["details"] == "pocket"


def test_create_account_requires_parent(client: TestClient):
    response = client.post("/accounts", data={"name": "x", "parent_id": ""})
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"


def test_create_account_shows_service_errors(client: TestClient, root_accounts: dict[str, str]):
    bank = _bank(client, root_accounts, "5.00")
    response = client.post("/accounts", data={"name": "child", "parent_id": bank["id"]})
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"
    assert "has postings" in response.text


def test_create_account_rejects_invalid_amount(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        "/accounts",
        data={"name": "x", "parent_id": root_accounts["Assets"], "balance": "abc"},
    )
    assert response.status_code == 400
    assert "not a valid amount" in response.text


def test_error_messages_are_escaped(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        "/accounts",
        data={"name": "x", "parent_id": root_accounts["Assets"], "balance": "<script>"},
    )
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text


# --- edit ------------------------------------------------------------------


def test_edit_page_prefills_and_limits_parents_to_same_root(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.get(f"/accounts/{account['id']}/edit")
    assert response.status_code == 200
    text = response.text
    assert 'value="checking"' in text
    assert f'value="{root_accounts["Assets"]}" selected' in text
    assert f'value="{root_accounts["Expenses"]}"' not in text
    assert f'<option value="{account["id"]}"' not in text
    assert f'hx-post="/accounts/{account["id"]}/delete"' in text


def test_update_account_from_form(client: TestClient, root_accounts: dict[str, str], account: dict):
    response = client.post(
        f"/accounts/{account['id']}/edit",
        data={
            "name": "main checking",
            "parent_id": root_accounts["Assets"],
            "details": "",
            "balance": "75.00",
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == f"/accounts/{account['id']}"
    updated = client.get(f"/api/accounts/{account['id']}").json()
    assert updated["name"] == "main checking"
    assert updated["balance"] == "75.00"


def test_update_account_unchanged_is_a_noop(client: TestClient, root_accounts: dict[str, str], account: dict):
    response = client.post(
        f"/accounts/{account['id']}/edit",
        data={"name": "checking", "parent_id": root_accounts["Assets"], "balance": "0.00"},
    )
    assert response.status_code == 200
    assert client.get("/api/transactions/").json() == []


def test_update_account_shows_service_errors(client: TestClient, root_accounts: dict[str, str], account: dict):
    response = client.post(
        f"/accounts/{account['id']}/edit",
        data={"name": "checking", "parent_id": root_accounts["Liabilities"]},
    )
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"
    assert "different root" in response.text


def test_update_missing_account_is_404(client: TestClient, root_accounts: dict[str, str]):
    response = client.post(
        f"/accounts/{MISSING}/edit",
        data={"name": "x", "parent_id": root_accounts["Assets"]},
    )
    assert response.status_code == 404


# --- delete ----------------------------------------------------------------


def test_delete_account_from_ui(client: TestClient, account: dict):
    response = client.post(f"/accounts/{account['id']}/delete")
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/accounts"
    assert client.get(f"/api/accounts/{account['id']}").status_code == 404


def test_delete_account_with_postings_shows_error(client: TestClient, root_accounts: dict[str, str]):
    bank = _bank(client, root_accounts, "5.00")
    response = client.post(f"/accounts/{bank['id']}/delete")
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#page-error"
    assert "has postings" in response.text


def test_expense_group_page_shows_direct_postings(client: TestClient, account: dict, expense_account: dict):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "30.00"),
                leg(account, "credit", "30.00"),
            ]
        },
    )
    post_account(client, {"name": "snacks", "parent_id": expense_account["id"]})

    text = client.get(f"/categories/{expense_account['id']}").text
    assert "posted to groceries itself" in text and "30.00" in text
    assert f"/transactions/new?category={expense_account['id']}" in text
    assert f"/categories/new?parent={expense_account['id']}" in text


def test_edit_is_the_first_row_of_the_one_menu(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "10"}).json()
    page = client.get(f"/accounts/{bank['id']}").text
    head, menu = page.split('<details class="menu">', 1)
    menu = menu.split("</details>", 1)[0]
    assert head.split("<h1>", 1)[1].count("circ-button") == 1, "the pin button is the only one beside the menu"
    assert "/edit" not in head, "no pencil of its own"
    assert menu.index(f'href="/accounts/{bank["id"]}/edit"') < menu.index("Close account")
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    cat = client.get(f"/categories/{food['id']}").text
    cat_head, cat_menu = cat.split('<details class="menu">', 1)
    assert "/edit" not in cat_head.split("<h1>", 1)[1]
    assert f'href="/categories/{food["id"]}/edit"' in cat_menu.split("</details>", 1)[0]
    roots_page = client.get(f"/accounts/{root_accounts['Assets']}").text
    assert f"/accounts/{root_accounts['Assets']}/edit" not in roots_page, "a top-level account cannot be edited"


def test_the_top_is_a_title_with_its_menu_then_the_figure_and_no_add_button(client, root_accounts):
    bank = post_account(
        client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "10", "details": "main account"}
    ).json()
    page = client.get(f"/accounts/{bank['id']}").text
    head = page.split('<header class="account-hero">', 1)[1].split("</header>", 1)[0]
    assert (
        head.index("<h1>Bank")
        < head.index('class="note-info"')
        < head.index('class="menu"')
        < head.index("hero-balance")
    )
    assert "Assets · main account" not in head and ">Other</p>" in head and ">Assets</p>" not in head, (
        "the small line is the kind (never the type); the note is behind the i"
    )
    assert "acct-add" not in page and "Add transaction" not in head, "the docked + already adds one for this account"


def test_a_category_has_the_month_pill_in_the_top_row_and_no_label(client, root_accounts):
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    page = client.get(f"/categories/{food['id']}").text
    nav = page.split('class="cat-bar acct-nav"', 1)[1].split('<header class="account-hero">', 1)[0]
    head = page.split('<header class="account-hero">', 1)[1].split("</header>", 1)[0]
    assert nav.index('class="back"') < nav.index("month-pill"), (
        "the back link and the month share one row above the title"
    )
    assert "month-pill" not in head and ">Spending</p>" in head, "the type stays under the title"
    assert "so far" not in head and "Spent" not in head and "Earned" not in head, "the figure needs no label"
    assert 'title="Previous month"' in nav and 'title="Next month"' not in nav, "nothing after the current month"
    assert "acct-add" not in page
    last = client.get(f"/categories/{food['id']}?month=2026-01").text
    assert 'title="Next month"' in last and "Jan 2026" in last


def test_green_and_plus_mean_money_in_on_a_bank_and_a_payment_into_a_card(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"}).json()
    card = post_account(client, {"name": "Visa", "parent_id": root_accounts["Liabilities"]}).json()
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    client.post(
        "/api/transactions/",
        json={
            "payee": "Dinner",
            "postings": [
                leg(food, "debit", "300"),
                leg(card, "credit", "300"),
            ],
        },
    )
    client.post(
        "/api/transactions/",
        json={
            "payee": "Pay the card",
            "postings": [
                leg(card, "debit", "100"),
                leg(bank, "credit", "100"),
            ],
        },
    )
    page = client.get(f"/accounts/{card['id']}").text.split("<h2>Transactions</h2>", 1)[1]
    assert page.count("tx-amount income") == 1 and "+100.00" in page, "the payment is green with a plus"
    assert "+300.00" not in page and "300.00" in page, "a charge is plain"
    bank_page = client.get(f"/accounts/{bank['id']}").text.split("<h2>Transactions</h2>", 1)[1]
    assert "+1,000.00" in bank_page and bank_page.count("tx-amount income") == 1, "money into a bank account is green"
    assert "+100.00" not in bank_page, "what leaves the bank is plain"


def test_upcoming_on_a_card_follows_the_same_rule(client, root_accounts):
    from datetime import timedelta

    from app.clock import local_today

    card = post_account(client, {"name": "Visa", "parent_id": root_accounts["Liabilities"]}).json()
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    client.post(
        "/api/transactions/",
        json={
            "date": str(local_today() + timedelta(days=9)),
            "payee": "Later",
            "postings": [
                leg(food, "debit", "70"),
                leg(card, "credit", "70"),
            ],
        },
    )
    page = client.get(f"/accounts/{card['id']}").text
    assert "1 upcoming" in page and "up-amount income" not in page and "+70.00" not in page


def test_an_upcoming_payment_into_a_card_is_green_and_a_charge_is_not(client, root_accounts):
    from datetime import timedelta

    from app.clock import local_today

    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"}).json()
    card = post_account(client, {"name": "Visa", "parent_id": root_accounts["Liabilities"], "balance": "500"}).json()
    client.post(
        "/api/transactions/",
        json={
            "date": str(local_today() + timedelta(days=9)),
            "payee": "Pay later",
            "postings": [
                leg(card, "debit", "200"),
                leg(bank, "credit", "200"),
            ],
        },
    )
    page = client.get(f"/accounts/{card['id']}").text
    assert "1 upcoming" in page and "+200.00" in page and "up-amount income" in page


def test_a_description_sits_behind_an_i_beside_the_name_not_under_it(client, root_accounts):
    made = post_account(
        client, {"name": "Wallet", "details": "Kept in the bag, for taxis", "parent_id": root_accounts["Assets"]}
    ).json()
    plain = post_account(client, {"name": "Spare", "parent_id": root_accounts["Assets"]}).json()
    page = client.get(f"/accounts/{made['id']}").text
    sub = page.split('<p class="acct-sub">', 1)[1].split("</p>", 1)[0]
    assert "Kept in the bag" not in sub and sub.strip() == "Other", "the line under the name is just the kind"
    info = page.split('<details class="note-info">', 1)[1].split("</details>", 1)[0]
    assert "Kept in the bag, for taxis" in info and 'aria-label="About Wallet"' in info
    assert 'class="note-info"' not in client.get(f"/accounts/{plain['id']}").text, "no description, no icon"

    cat = post_account(client, {"name": "Taxis", "details": "Only cabs", "parent_id": root_accounts["Expenses"]}).json()
    category_page = client.get(f"/categories/{cat['id']}").text
    assert "Only cabs" in category_page.split('<details class="note-info">', 1)[1].split("</details>", 1)[0]
    assert "Only cabs" not in category_page.split('<p class="acct-sub">', 1)[1].split("</p>", 1)[0]


def test_an_account_with_sub_accounts_lists_them_not_their_transactions(
    client: TestClient, root_accounts: dict[str, str]
):
    banks = post_account(client, {"name": "Banks", "parent_id": root_accounts["Assets"]}).json()
    hdfc = post_account(client, {"name": "HDFC", "parent_id": banks["id"], "balance": "500.00"}).json()
    post_account(client, {"name": "ICICI", "parent_id": banks["id"], "balance": "250.00"})
    shop = post_account(client, {"name": "Shopping", "parent_id": root_accounts["Expenses"]}).json()
    client.post(
        "/api/transactions/",
        json={
            "payee": "Gadget Store",
            "postings": [
                leg(shop, "debit", "40.00"),
                leg(hdfc, "credit", "40.00"),
            ],
        },
    )

    group = client.get(f"/accounts/{banks['id']}").text
    assert "<h2>Accounts</h2>" in group and "<h2>Sub-accounts</h2>" not in group and "acc-rail" in group
    assert f'href="/accounts/{hdfc["id"]}"' in group and "HDFC" in group and "ICICI" in group
    assert "460.00" in group and "250.00" in group, "each account's balance"
    assert f"/accounts/new?parent={banks['id']}" in group, "the add card adds another"
    assert "<h2>Transactions</h2>" in group and "Gadget Store" in group, "the entries of its accounts"
    leaf = client.get(f"/accounts/{hdfc['id']}").text
    assert "Gadget Store" in leaf and "<h2>Accounts</h2>" not in leaf


# --- the new-account form asks about the budget ---------------------------------------------------------------


def _made(client: TestClient, name: str) -> dict:
    return next(a for a in client.get("/api/accounts/").json() if a["name"] == name)


def test_the_new_account_form_asks_whether_it_is_part_of_the_budget(client: TestClient, root_accounts: dict[str, str]):
    page = client.get(f"/accounts/new?parent={root_accounts['Assets']}").text
    assert "data-budget-fields" in page and 'name="on_budget"' in page and 'name="budget_choice"' in page
    assert 'name="on_budget" value="1" checked' in page, "an asset starts in the budget"
    assert "Usual category" not in page and 'name="payment_category"' not in page, "nothing is chosen for payments"
    assert 'data-root="Assets"' in page
    liability = client.get(f"/accounts/new?parent={root_accounts['Liabilities']}").text
    assert 'name="on_budget" value="1" checked' not in liability, "a card or loan starts outside it"
    assert "data-budget-fields" in client.get("/accounts/new").text, (
        "the fields are there for the chosen parent to show"
    )
    assert "data-budget-fields" not in client.get("/categories/new").text, "categories have none"


def test_creating_an_account_follows_the_budget_choice(client: TestClient, root_accounts: dict[str, str]):
    base = {"budget_choice": "1"}
    client.post("/accounts", data={**base, "name": "Savings", "parent_id": root_accounts["Assets"], "on_budget": "1"})
    assert _made(client, "Savings")["on_budget"] is True
    client.post("/accounts", data={**base, "name": "Fund", "parent_id": root_accounts["Assets"]})
    assert _made(client, "Fund")["on_budget"] is False, "the box was left off"
    client.post("/accounts", data={**base, "name": "Car loan", "parent_id": root_accounts["Liabilities"]})
    assert _made(client, "Car loan")["on_budget"] is False, "a loan left out of the budget"
    client.post("/accounts", data={"name": "Wallet", "parent_id": root_accounts["Assets"]})
    assert _made(client, "Wallet")["on_budget"] is True, "no choice sent: an asset defaults to in"


def test_the_add_account_card_of_the_plain_accounts_opens_the_form_on_their_type(
    client: TestClient, root_accounts: dict[str, str]
):
    post_account(client, {"name": "Visa", "parent_id": root_accounts["Liabilities"]})
    page = client.get("/accounts").text
    assert 'href="/accounts/new?root=liabilities"' in page and ">Other you owe<" in page
    form = client.get("/accounts/new?root=liabilities").text
    assert 'data-root="Liabilities"' in form and 'data-root="Assets"' not in form
    assert f'value="{root_accounts["Liabilities"]}" selected' in form, "it starts on the type itself"
    assert "Amount you owe now" in form
    assert 'data-root="Assets"' in client.get("/accounts/new?root=assets").text


# --- going back keeps the chip ---------------------------------------------


def _under(client, root_accounts, root, name, **extra):
    return post_account(client, {"name": name, "parent_id": root_accounts[root], **extra}).json()


def test_the_back_link_goes_to_the_accounts_page(client: TestClient, root_accounts: dict[str, str]):
    card = _under(client, root_accounts, "Liabilities", "Cards")
    inner = post_account(client, {"name": "Visa", "parent_id": card["id"]}).json()
    equity = _under(client, root_accounts, "Equity", "Capital")
    bank = _under(client, root_accounts, "Assets", "Bank")
    for account in (card, inner, equity, bank):
        text = client.get(f"/accounts/{account['id']}").text
        assert 'class="back" href="/accounts"' in text, account["name"]


def test_after_closing_or_deleting_you_land_on_the_accounts_page(client: TestClient, root_accounts: dict[str, str]):
    card = _under(client, root_accounts, "Liabilities", "Visa")
    gone = _under(client, root_accounts, "Liabilities", "Old loan")
    assert client.post(f"/accounts/{card['id']}/close").headers["HX-Redirect"] == "/accounts"
    assert client.post(f"/accounts/{gone['id']}/delete").headers["HX-Redirect"] == "/accounts"


def test_the_new_account_page_goes_back_to_the_accounts_page(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/accounts/new?root=liabilities").text
    assert 'class="back" href="/accounts"' in text
    income = client.get("/categories/new?root=income").text
    assert 'class="back" href="/categories?tab=income"' in income


def test_groups_the_person_made_are_kinds_and_the_plain_accounts_come_last(
    client: TestClient, root_accounts: dict[str, str]
):
    """Alphabetically Apple, Banks and Cash interleave; the page puts the groups first, then the plain ones together."""

    def make(name, parent):
        return post_account(client, {"name": name, "parent_id": parent, "balance": "10"}).json()

    assets = root_accounts["Assets"]
    make("Apple", assets)
    banks = post_account(client, {"name": "Banks", "parent_id": assets}).json()
    make("HDFC", banks["id"])
    make("Cash", assets)
    zoo = post_account(client, {"name": "Zoo", "parent_id": assets}).json()
    make("Lion", zoo["id"])
    text = client.get("/accounts").text
    heads = re.findall(r"<h2>(?:<a [^>]*>)?([^<]+)(?:</a>)?</h2>", text)
    assert heads == ["Banks", "Zoo", "Other"], heads
    assert text.count('<section class="acc-kind') == 3
    assert "20.00 · 2 accounts" in text, "Apple and Cash, 10 each"


def test_equity_is_not_on_the_page(client: TestClient, root_accounts: dict[str, str]):
    _bank(client, root_accounts)
    page = client.get("/accounts").text
    assert "Opening Balances" not in page and "Equity" not in page and "?tab=" not in page


def test_the_plus_in_the_bar_on_an_account_page_starts_an_entry_for_it_and_comes_back(
    client: TestClient, account: dict
):
    page = client.get(f"/accounts/{account['id']}").text
    here = f"/transactions/new?account={account['id']}&amp;back=/accounts/{account['id']}"
    assert f'class="fab" href="{here}"' in page, "the docked plus"
    assert f'sidebar-new" href="{here}"' in page, "the sidebar's button on a wide screen"


def test_the_plus_is_the_usual_one_where_the_page_cannot_be_posted_to(
    client: TestClient, root_accounts: dict[str, str]
):
    group = client.get(f"/accounts/{root_accounts['Assets']}").text
    assert 'class="fab" href="/transactions/new"' in group
    assert 'class="fab" href="/transactions/new"' in client.get("/").text
