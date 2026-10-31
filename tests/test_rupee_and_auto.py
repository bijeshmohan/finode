"""The rupee sign in place of "INR", and blue for what was added automatically."""

from app.templating import amount, symbol

from .books import leg, post_account
from .test_budget import account, assign


def test_the_rupee_sign_goes_in_front_and_other_currencies_keep_their_code():
    assert symbol("INR") == "\u20b9" and symbol("USD") == "USD" and symbol(None) == ""
    assert amount("1,200.00", "INR") == "\u20b91,200.00"
    assert amount("\u22125.00", "INR") == "\u20b9\u22125.00", (
        "a negative keeps its minus next to the digits, after the sign"
    )
    assert amount("40.00", "USD") == "40.00 USD"


def test_the_big_figures_use_the_sign_and_the_font_carries_it(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="1000")
    food = account(client, root_accounts, "Food", "Expenses")
    assign(client, food, "100")
    budget = client.get("/budget").text
    assert '<span class="figure"><span class="cur">&#8377;</span>900.00</span>' in budget, (
        "the head is ready to assign: 1000 in the bank, 100 assigned"
    )
    assert "INR</span>" not in budget.split('class="ready')[1].split("</div>")[0]
    from .test_budget import move

    move(client, bank, food, "30")
    home = client.get("/").text
    assert '<span class="cur">&#8377;</span>' in home
    assert "fonts/figtree-rupee.woff2" in home and "unicode-range:U+20B9" in home, (
        "the sign comes from our own font, not the phone's"
    )


def test_what_was_added_automatically_is_blue(client):
    from pathlib import Path

    css = (Path(__file__).parent.parent / "app" / "static" / "style.css").read_text()
    assert ".tx-via {" in css and "color: var(--auto)" in css.split(".tx-via {")[1].split("}")[0]
    assert "color: var(--auto)" in css.split(".sheet-tags a {")[1].split("}")[0], "the sheet's tags are blue links"
    tokens = [block for block in css.split("{") if "--auto:" in block]
    assert len(tokens) == 3, "light and both dark blocks define it"


def test_an_account_page_shows_the_rupee_sign_like_a_category_page(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1234567"}).json()
    page = client.get(f"/accounts/{bank['id']}").text
    assert '<p class="hero-balance"><span class="cur">&#8377;</span>12,34,567.00</p>' in page
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    assert '<span class="cur">&#8377;</span>0.00' in client.get(f"/categories/{food['id']}").text
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(food, "debit", "75"),
                leg(bank, "credit", "75"),
            ]
        },
    )
    client.patch(f"/api/accounts/{bank['id']}", json={"balance": "-75"})
    overdrawn = client.get(f"/accounts/{bank['id']}").text
    assert '<span class="cur">&#8377;</span>\u2212' in overdrawn, "a negative keeps its minus after the sign"
    assert '&minus;<span class="cur">' not in overdrawn


def test_another_currency_keeps_its_code_after_the_figure_on_an_account_page(client, root_accounts):
    client.patch("/api/profile/", json={"default_currency": "USD"})
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "40"}).json()
    page = client.get(f"/accounts/{bank['id']}").text
    assert '<p class="hero-balance">40.00<small>USD</small></p>' in page
