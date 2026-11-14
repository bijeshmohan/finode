"""Home in the React app, in a browser (ports of the Home tests in test_transactions_page.py and test_budget_page.py)."""

import re

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def shop(api: Api, books, payee: str, on: str | None = None):
    return api.post(
        "/transactions/",
        payee=payee,
        **({"date": on} if on else {}),
        postings=[leg(books["food"], "debit", "10"), leg(books["checking"], "credit", "10")],
    )


def test_the_sheet_opens_from_home_too(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    shop(spa_api, spa_books, "Swiggy")
    page.goto("/")
    page.get_by_role("button", name=re.compile("^Swiggy")).click()
    expect(page.get_by_role("dialog", name="Transaction details")).to_contain_text("Paid from")
    assert page.url.split("?")[0].rstrip("/").count("/") == 2, "still on Home"


def test_home_starts_short_and_show_more_finishes_the_month(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    for i in range(14):
        shop(spa_api, spa_books, f"Shop {i:02d}", f"2026-01-{i + 1:02d}")
    page.goto("/?month=2026-01")
    shops = page.get_by_role("button", name=re.compile(r"^Shop "))
    expect(shops).to_have_count(8)
    page.get_by_role("button", name=re.compile("Show 6 more")).click()
    expect(shops).to_have_count(14)
    expect(page.get_by_text(re.compile("That is all of January"))).to_be_visible()
    shops.last.click()  # rows that arrived later open the details sheet too
    expect(page.get_by_role("dialog", name="Transaction details")).to_be_visible()


def test_home_is_centred_beside_the_sidebar_and_its_day_label_lines_up(
    signed_in_spa_page: Page, spa_books, spa_api: Api
):
    page = signed_in_spa_page
    shop(spa_api, spa_books, "Lunch")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/")
    expect(page.get_by_role("heading", name="Transactions")).to_be_visible()
    column = page.evaluate("""() => {
      const main = document.querySelector('main').getBoundingClientRect();
      const side = document.querySelector('aside').getBoundingClientRect();
      return [main.left - side.right, innerWidth - main.right];
    }""")
    assert abs(column[0] - column[1]) <= 2, f"equal space on both sides of the column: {column}"
    heading = page.get_by_role("heading", name="Transactions").bounding_box()
    day = page.get_by_role("heading", level=3).first.bounding_box()
    assert heading and day and abs(heading["x"] - day["x"]) <= 1, "the day label starts where the heading does"


def test_deleting_on_home_after_show_more_leaves_no_duplicates(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    for i in range(14):
        shop(spa_api, spa_books, f"Shop {i:02d}", f"2026-01-{i + 1:02d}")
    page.goto("/?month=2026-01")
    shops = page.get_by_role("button", name=re.compile(r"^Shop "))
    page.get_by_role("button", name=re.compile("Show 6 more")).click()
    expect(shops).to_have_count(14)
    page.get_by_role("button", name=re.compile("^Shop 12")).click()
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("dialog", name="Transaction details").get_by_role("button", name="Delete").click()
    expect(shops).to_have_count(13)
    titles = [t.split("\n")[0] for t in shops.all_inner_texts()]
    assert len(titles) == len(set(titles)), "no entry twice"
