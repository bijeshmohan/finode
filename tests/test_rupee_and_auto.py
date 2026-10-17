"""The rupee sign in place of "INR", and blue for what was added automatically."""

from decimal import Decimal

from app.templating import amount, symbol
from .test_budget import account, assign


def test_the_rupee_sign_goes_in_front_and_other_currencies_keep_their_code():
    assert symbol("INR") == "\u20b9" and symbol("USD") == "USD" and symbol(None) == ""
    assert amount("1,200.00", "INR") == "\u20b91,200.00"
    assert amount("\u22125.00", "INR") == "\u2212\u20b95.00", "a negative keeps its minus in front of the sign"
    assert amount("40.00", "USD") == "40.00 USD"


def test_the_big_figures_use_the_sign_and_the_font_carries_it(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="1000")
    food = account(client, root_accounts, "Food", "Expenses")
    assign(client, food, "100")
    budget = client.get("/budget").text
    assert '<span class="figure "><span class="cur">&#8377;</span>100.00</span>' in budget, "left to spend"
    assert "INR</span>" not in budget.split('class="ready')[1].split("</div>")[0]
    from .test_budget import move

    move(client, bank, food, "30")
    home = client.get("/").text
    assert '<span class="cur">&#8377;</span>' in home
    assert "fonts/figtree-rupee.woff2" in home and "unicode-range:U+20B9" in home, "the sign comes from our own font, not the phone's"


def test_what_was_added_automatically_is_blue(client):
    from pathlib import Path

    css = (Path(__file__).parent.parent / "app" / "static" / "style.css").read_text()
    assert ".tx-via {" in css and "color: var(--auto)" in css.split(".tx-via {")[1].split("}")[0]
    tokens = [block for block in css.split("{") if "--auto:" in block]
    assert len(tokens) == 3, "light and both dark blocks define it"
