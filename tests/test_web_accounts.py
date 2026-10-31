from datetime import date

from fastapi.testclient import TestClient

from .books import post_account

MISSING = "00000000-0000-4000-8000-0000000000ff"


def _opening_balances(client: TestClient) -> dict:
    return next(a for a in client.get("/api/accounts/").json() if a["name"] == "Opening Balances")


def _bank(client: TestClient, root_accounts: dict[str, str], balance: str = "100.00") -> dict:
    return post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": balance}).json()


# --- accounts list ---------------------------------------------------------


def test_accounts_page_groups_accounts_under_roots_in_order(
    client: TestClient, root_accounts: dict[str, str], account: dict
):
    response = client.get("/accounts")
    assert response.status_code == 200
    text = response.text
    assert text.index(">Asset<") < text.index(">Liability<") and ">Equity<" not in text, "Equity has no chip"
    assert ">Expenses<" not in text and ">Income<" not in text, "those are on the Categories page"
    assert f'href="/accounts/{account["aid"]}"' in text
    assert "checking" in text


def test_accounts_page_suggests_first_account_for_empty_roots(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/accounts?tab=liabilities").text
    assert ('href="/accounts/new?root=liabilities"') in text
    assert 'class="button"' in text and "Add account" in text, "an empty type offers an Add account pill"


def test_accounts_page_marks_system_account(client: TestClient, root_accounts: dict[str, str]):
    _bank(client, root_accounts)
    assert '<span class="badge">system</span>' in client.get("/accounts?tab=equity").text


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
                {"account": expense_account["aid"], "side": "debit", "amount": "30.00"},
                {"account": bank["aid"], "side": "credit", "amount": "30.00"},
            ],
        },
    )

    text = client.get(f"/accounts/{bank['aid']}").text
    assert "70.00" in text
    assert "lunch" in text and "30.00" in text and "−30.00" not in text
    assert f'href="/transactions/new?account={bank["aid"]}&back=/accounts/{bank["aid"]}"' in text
    assert f'href="/accounts/{bank["aid"]}/edit"' in text
    # it has postings, so it cannot gain sub-accounts
    assert f"/accounts/new?parent={bank['aid']}" not in text


def test_account_page_for_empty_leaf_offers_sub_account(client: TestClient, account: dict):
    text = client.get(f"/accounts/{account['aid']}").text
    assert f"/accounts/new?parent={account['aid']}" in text
    assert "No transactions yet." in text


def test_root_and_system_account_pages_are_read_only(client: TestClient, root_accounts: dict[str, str]):
    _bank(client, root_accounts)
    for aid in (root_accounts["Assets"], _opening_balances(client)["aid"]):
        assert f"/accounts/{aid}/edit" not in client.get(f"/accounts/{aid}").text
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
    assert response.headers["HX-Redirect"] == f"/accounts/{created['aid']}"
    assert created["balance"] == "1250.50"
    assert created["details"] == "pocket"


def test_create_account_requires_parent(client: TestClient):
    response = client.post("/accounts", data={"name": "x", "parent_id": ""})
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#form-error"


def test_create_account_shows_service_errors(client: TestClient, root_accounts: dict[str, str]):
    bank = _bank(client, root_accounts, "5.00")
    response = client.post("/accounts", data={"name": "child", "parent_id": bank["aid"]})
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
    response = client.get(f"/accounts/{account['aid']}/edit")
    assert response.status_code == 200
    text = response.text
    assert 'value="checking"' in text
    assert f'value="{root_accounts["Assets"]}" selected' in text
    assert f'value="{root_accounts["Expenses"]}"' not in text
    assert f'<option value="{account["aid"]}"' not in text
    assert f'hx-post="/accounts/{account["aid"]}/delete"' in text


def test_update_account_from_form(client: TestClient, root_accounts: dict[str, str], account: dict):
    response = client.post(
        f"/accounts/{account['aid']}/edit",
        data={
            "name": "main checking",
            "parent_id": root_accounts["Assets"],
            "details": "",
            "balance": "75.00",
        },
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == f"/accounts/{account['aid']}"
    updated = client.get(f"/api/accounts/{account['aid']}").json()
    assert updated["name"] == "main checking"
    assert updated["balance"] == "75.00"


def test_update_account_unchanged_is_a_noop(client: TestClient, root_accounts: dict[str, str], account: dict):
    response = client.post(
        f"/accounts/{account['aid']}/edit",
        data={"name": "checking", "parent_id": root_accounts["Assets"], "balance": "0.00"},
    )
    assert response.status_code == 200
    assert client.get("/api/transactions/").json() == []


def test_update_account_shows_service_errors(client: TestClient, root_accounts: dict[str, str], account: dict):
    response = client.post(
        f"/accounts/{account['aid']}/edit",
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
    response = client.post(f"/accounts/{account['aid']}/delete")
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/accounts?tab=assets"
    assert client.get(f"/api/accounts/{account['aid']}").status_code == 404


def test_delete_account_with_postings_shows_error(client: TestClient, root_accounts: dict[str, str]):
    bank = _bank(client, root_accounts, "5.00")
    response = client.post(f"/accounts/{bank['aid']}/delete")
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#page-error"
    assert "has postings" in response.text


def test_expense_group_page_shows_direct_postings(client: TestClient, account: dict, expense_account: dict):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "30.00"},
                {"account": account["aid"], "side": "credit", "amount": "30.00"},
            ]
        },
    )
    post_account(client, {"name": "snacks", "parent_id": expense_account["aid"]})

    text = client.get(f"/categories/{expense_account['aid']}").text
    assert "posted to groceries itself" in text and "30.00" in text
    assert f"/transactions/new?category={expense_account['aid']}" in text
    assert f"/categories/new?parent={expense_account['aid']}" in text


def test_the_edit_button_is_beside_the_menu_not_inside_it(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "10"}).json()
    page = client.get(f"/accounts/{bank['aid']}").text
    head, menu = page.split('<details class="menu">', 1)
    assert f'class="circ-button" href="/accounts/{bank["aid"]}/edit"' in head and 'title="Edit"' in head
    assert f"/accounts/{bank['aid']}/edit" not in menu.split("</details>", 1)[0], "it left the menu"
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    cat = client.get(f"/categories/{food['aid']}").text
    assert f'class="circ-button" href="/categories/{food["aid"]}/edit"' in cat.split('<details class="menu">', 1)[0]
    roots_page = client.get(f"/accounts/{root_accounts['Assets']}").text
    assert f"/accounts/{root_accounts['Assets']}/edit" not in roots_page, "a top-level account cannot be edited"


def test_the_top_is_a_title_with_its_actions_then_the_figure_and_a_wide_add_button(client, root_accounts):
    bank = post_account(
        client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "10", "details": "main account"}
    ).json()
    page = client.get(f"/accounts/{bank['aid']}").text
    head = page.split('<header class="account-hero">', 1)[1].split("</header>", 1)[0]
    assert (
        head.index("<h1>Bank")
        < head.index('class="note-info"')
        < head.index('title="Edit"')
        < head.index('class="menu"')
        < head.index("hero-balance")
        < head.index("acct-add")
    )
    assert "Assets · main account" not in head and ">Assets</p>" in head, (
        "the small line is the type; the note is behind the i"
    )
    assert 'class="button acct-add"' in head and "Add transaction" in head


def test_a_category_has_the_month_pill_in_the_top_row_and_no_label(client, root_accounts):
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    page = client.get(f"/categories/{food['aid']}").text
    nav = page.split('class="cat-bar acct-nav"', 1)[1].split('<header class="account-hero">', 1)[0]
    head = page.split('<header class="account-hero">', 1)[1].split("</header>", 1)[0]
    assert nav.index('class="back"') < nav.index("month-pill"), (
        "the back link and the month share one row above the title"
    )
    assert "month-pill" not in head and ">Spending</p>" in head, "the type stays under the title"
    assert "so far" not in head and "Spent" not in head and "Earned" not in head, "the figure needs no label"
    assert 'title="Previous month"' in nav and 'title="Next month"' not in nav, "nothing after the current month"
    assert "acct-add" not in page, "adding is a + on the Transactions heading"
    last = client.get(f"/categories/{food['aid']}?month=2026-01").text
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
                {"account": food["aid"], "side": "debit", "amount": "300"},
                {"account": card["aid"], "side": "credit", "amount": "300"},
            ],
        },
    )
    client.post(
        "/api/transactions/",
        json={
            "payee": "Pay the card",
            "postings": [
                {"account": card["aid"], "side": "debit", "amount": "100"},
                {"account": bank["aid"], "side": "credit", "amount": "100"},
            ],
        },
    )
    page = client.get(f"/accounts/{card['aid']}").text.split("<h2>Transactions</h2>", 1)[1]
    assert page.count("tx-amount income") == 1 and "+100.00" in page, "the payment is green with a plus"
    assert "+300.00" not in page and "300.00" in page, "a charge is plain"
    bank_page = client.get(f"/accounts/{bank['aid']}").text.split("<h2>Transactions</h2>", 1)[1]
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
                {"account": food["aid"], "side": "debit", "amount": "70"},
                {"account": card["aid"], "side": "credit", "amount": "70"},
            ],
        },
    )
    page = client.get(f"/accounts/{card['aid']}").text
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
                {"account": card["aid"], "side": "debit", "amount": "200"},
                {"account": bank["aid"], "side": "credit", "amount": "200"},
            ],
        },
    )
    page = client.get(f"/accounts/{card['aid']}").text
    assert "1 upcoming" in page and "+200.00" in page and "up-amount income" in page


def test_a_description_sits_behind_an_i_beside_the_name_not_under_it(client, root_accounts):
    made = post_account(
        client, {"name": "Wallet", "details": "Kept in the bag, for taxis", "parent_id": root_accounts["Assets"]}
    ).json()
    plain = post_account(client, {"name": "Spare", "parent_id": root_accounts["Assets"]}).json()
    page = client.get(f"/accounts/{made['aid']}").text
    sub = page.split('<p class="acct-sub">', 1)[1].split("</p>", 1)[0]
    assert "Kept in the bag" not in sub and sub.strip() == "Assets", "the line under the name is just the type"
    info = page.split('<details class="note-info">', 1)[1].split("</details>", 1)[0]
    assert "Kept in the bag, for taxis" in info and 'aria-label="About Wallet"' in info
    assert 'class="note-info"' not in client.get(f"/accounts/{plain['aid']}").text, "no description, no icon"

    cat = post_account(client, {"name": "Taxis", "details": "Only cabs", "parent_id": root_accounts["Expenses"]}).json()
    category_page = client.get(f"/categories/{cat['aid']}").text
    assert "Only cabs" in category_page.split('<details class="note-info">', 1)[1].split("</details>", 1)[0]
    assert "Only cabs" not in category_page.split('<p class="acct-sub">', 1)[1].split("</p>", 1)[0]


def test_an_account_with_sub_accounts_lists_them_not_their_transactions(
    client: TestClient, root_accounts: dict[str, str]
):
    banks = post_account(client, {"name": "Banks", "parent_id": root_accounts["Assets"]}).json()
    hdfc = post_account(client, {"name": "HDFC", "parent_id": banks["aid"], "balance": "500.00"}).json()
    post_account(client, {"name": "ICICI", "parent_id": banks["aid"], "balance": "250.00"})
    shop = post_account(client, {"name": "Shopping", "parent_id": root_accounts["Expenses"]}).json()
    client.post(
        "/api/transactions/",
        json={
            "payee": "Gadget Store",
            "postings": [
                {"account": shop["aid"], "side": "debit", "amount": "40.00"},
                {"account": hdfc["aid"], "side": "credit", "amount": "40.00"},
            ],
        },
    )

    group = client.get(f"/accounts/{banks['aid']}").text
    assert "Gadget Store" not in group and "Opening balance" not in group, "their entries are on their own pages"
    assert "<h2>Sub-accounts</h2>" in group and "<h2>Transactions</h2>" not in group
    assert f'href="/accounts/{hdfc["aid"]}"' in group and "HDFC" in group and "ICICI" in group
    assert "460.00" in group and "250.00" in group, "each sub-account's balance"
    assert f"/accounts/new?parent={banks['aid']}" in group, "the + adds another"
    leaf = client.get(f"/accounts/{hdfc['aid']}").text
    assert "Gadget Store" in leaf and "<h2>Sub-accounts</h2>" not in leaf


# --- the new-account form asks about the budget ---------------------------------------------------------------


def _made(client: TestClient, name: str) -> dict:
    return next(a for a in client.get("/api/accounts/").json() if a["name"] == name)


def test_the_new_account_form_asks_whether_it_is_part_of_the_budget(client: TestClient, root_accounts: dict[str, str]):
    expense = post_account(client, {"name": "EMI", "parent_id": root_accounts["Expenses"]}).json()
    page = client.get(f"/accounts/new?parent={root_accounts['Assets']}").text
    assert "data-budget-fields" in page and 'name="on_budget"' in page and 'name="budget_choice"' in page
    assert 'name="on_budget" value="1" checked' in page, "an asset starts in the budget"
    assert "Usual category for payments" in page and f'<option value="{expense["aid"]}"' in page
    assert 'data-root="Assets"' in page and 'data-root="Liabilities"' in page and 'data-root="Equity"' in page
    liability = client.get(f"/accounts/new?parent={root_accounts['Liabilities']}").text
    assert 'name="on_budget" value="1" checked' not in liability, "a card or loan starts outside it"
    assert "data-budget-fields" in client.get("/accounts/new").text, (
        "the fields are there for the chosen parent to show"
    )
    assert "data-budget-fields" not in client.get("/categories/new").text, "categories have none"


def test_creating_an_account_follows_the_budget_choice(client: TestClient, root_accounts: dict[str, str]):
    emi = post_account(client, {"name": "EMI", "parent_id": root_accounts["Expenses"]}).json()
    base = {"budget_choice": "1"}
    client.post("/accounts", data={**base, "name": "Savings", "parent_id": root_accounts["Assets"], "on_budget": "1"})
    assert _made(client, "Savings")["on_budget"] is True
    client.post("/accounts", data={**base, "name": "Fund", "parent_id": root_accounts["Assets"]})
    assert _made(client, "Fund")["on_budget"] is False, "the box was left off"
    client.post(
        "/accounts",
        data={**base, "name": "Car loan", "parent_id": root_accounts["Liabilities"], "payment_category": emi["aid"]},
    )
    loan = _made(client, "Car loan")
    assert loan["on_budget"] is False and loan["payment_category_id"] == emi["aid"]
    client.post("/accounts", data={"name": "Wallet", "parent_id": root_accounts["Assets"]})
    assert _made(client, "Wallet")["on_budget"] is True, "no choice sent: an asset defaults to in"


def test_a_payment_category_only_goes_with_an_account_outside_the_budget(
    client: TestClient, root_accounts: dict[str, str]
):
    emi = post_account(client, {"name": "EMI", "parent_id": root_accounts["Expenses"]}).json()
    client.post(
        "/accounts",
        data={
            "budget_choice": "1",
            "on_budget": "1",
            "name": "A1",
            "parent_id": root_accounts["Assets"],
            "payment_category": emi["aid"],
        },
    )
    a1 = _made(client, "A1")
    assert a1["on_budget"] is True and a1["payment_category_id"] is None, "in the budget: the choice is ignored"
    other = client.post(
        "/accounts",
        data={
            "budget_choice": "1",
            "name": "A2",
            "parent_id": root_accounts["Assets"],
            "payment_category": root_accounts["Assets"],
        },
    )
    assert other.headers.get("HX-Retarget") == "#form-error", "it must be an expense category"
    assert not any(a["name"] == "A2" for a in client.get("/api/accounts/").json()), "nothing is left half made"


def test_the_plus_on_a_type_tab_offers_only_that_type(client: TestClient, root_accounts: dict[str, str]):
    page = client.get("/accounts?tab=liabilities").text
    assert 'href="/accounts/new?root=liabilities"' in page
    form = client.get("/accounts/new?root=liabilities").text
    assert 'data-root="Liabilities"' in form
    assert 'data-root="Assets"' not in form and 'data-root="Equity"' not in form
    assert f'value="{root_accounts["Liabilities"]}" selected' in form, "it starts on the type itself"
    assert 'data-root="Assets"' in client.get("/accounts/new?root=assets").text
    assert 'data-root="Liabilities"' not in client.get("/accounts/new?root=assets").text
    assert 'data-root="Liabilities"' in client.get("/accounts/new").text, "no tab: everything, as before"


# --- going back keeps the chip ---------------------------------------------


def _under(client, root_accounts, root, name, **extra):
    return post_account(client, {"name": name, "parent_id": root_accounts[root], **extra}).json()


def test_the_back_link_goes_to_the_chip_the_account_is_under(client: TestClient, root_accounts: dict[str, str]):
    card = _under(client, root_accounts, "Liabilities", "Cards")
    inner = post_account(client, {"name": "Visa", "parent_id": card["aid"]}).json()
    equity = _under(client, root_accounts, "Equity", "Capital")
    bank = _under(client, root_accounts, "Assets", "Bank")
    for account, tab in ((card, "liabilities"), (inner, "liabilities"), (equity, "equity"), (bank, "assets")):
        text = client.get(f"/accounts/{account['aid']}").text
        assert f'class="back" href="/accounts?tab={tab}"' in text, (account["name"], tab)


def test_after_closing_or_deleting_you_land_on_the_chip_it_was_under(client: TestClient, root_accounts: dict[str, str]):
    card = _under(client, root_accounts, "Liabilities", "Visa")
    gone = _under(client, root_accounts, "Liabilities", "Old loan")
    assert client.post(f"/accounts/{card['aid']}/close").headers["HX-Redirect"] == "/accounts?tab=liabilities"
    assert client.post(f"/accounts/{gone['aid']}/delete").headers["HX-Redirect"] == "/accounts?tab=liabilities"


def test_the_new_account_page_goes_back_to_its_chip(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/accounts/new?root=liabilities").text
    assert 'class="back" href="/accounts?tab=liabilities"' in text
    income = client.get("/categories/new?root=income").text
    assert 'class="back" href="/categories?tab=income"' in income


def test_accounts_without_a_group_are_listed_together_after_all_the_groups(
    client: TestClient, root_accounts: dict[str, str]
):
    """Alphabetically Apple, Banks and Cash interleave; the page puts the plain ones (Apple, Cash) last, together."""

    def make(name, parent):
        return post_account(client, {"name": name, "parent_id": parent, "balance": "10"}).json()

    assets = root_accounts["Assets"]
    make("Apple", assets)
    banks = post_account(client, {"name": "Banks", "parent_id": assets}).json()
    make("HDFC", banks["aid"])
    make("Cash", assets)
    zoo = post_account(client, {"name": "Zoo", "parent_id": assets}).json()
    make("Lion", zoo["aid"])
    text = client.get("/accounts").text
    order = [text.index(f'data-path="assets › {p}') for p in ("banks › hdfc", "zoo › lion", "apple", "cash")]
    assert order == sorted(order), "the groups come first, then Apple and Cash"
    assert text.count('class="acc-block') == 3, "two groups and one block of plain accounts"
    assert "data-others" in text and text.index("data-others") > text.index('data-path="assets › zoo › lion"')
    assert "<span>Others</span><span>20.00</span>" in text, "Apple and Cash, 10 each"


def test_equity_is_the_page_you_get_when_neither_chip_is_chosen(client: TestClient, root_accounts: dict[str, str]):
    _bank(client, root_accounts)
    assets = client.get("/accounts").text
    assert 'href="/accounts?tab=equity"' in assets and 'aria-pressed="true"' in assets, (
        "tapping the chosen chip again leaves none chosen"
    )
    assert 'href="/accounts?tab=liabilities"' in assets
    equity = client.get("/accounts?tab=equity").text
    assert 'aria-pressed="true"' not in equity, "neither chip is chosen"
    assert 'href="/accounts?tab=assets"' in equity and 'href="/accounts?tab=liabilities"' in equity
    assert "Opening Balances" in equity and "Equity" in equity
    liabilities = client.get("/accounts?tab=liabilities").text
    assert 'href="/accounts?tab=equity"' in liabilities and 'href="/accounts?tab=assets"' in liabilities


def test_others_is_not_shown_when_there_are_no_groups_or_for_equity(client: TestClient, root_accounts: dict[str, str]):
    post_account(client, {"name": "Apple", "parent_id": root_accounts["Assets"], "balance": "10"})
    assert "data-others" not in client.get("/accounts").text, "nothing to tell apart from"
    assert "data-others" not in client.get("/accounts?tab=equity").text
