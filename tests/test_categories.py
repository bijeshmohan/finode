"""The Categories page: where money goes and comes from, for one month; the Accounts page keeps the rest."""

from datetime import date, timedelta

import pytest

from .test_budget import account, move

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="10000")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": food["aid"]}).json()
    dining = client.post("/api/accounts/", json={"name": "Dining", "parent_id": food["aid"]}).json()
    rent = account(client, root_accounts, "Rent", "Expenses")
    travel = account(client, root_accounts, "Travel", "Expenses")
    return {"bank": bank, "salary": salary, "food": food, "groceries": groceries, "dining": dining, "rent": rent, "travel": travel}


def entry(client, debit, credit, amount, when):
    response = client.post("/api/transactions/", json={"date": when.isoformat(), "postings": [
        {"account": debit["aid"], "side": "debit", "amount": amount},
        {"account": credit["aid"], "side": "credit", "amount": amount}]})
    assert response.status_code == 201, response.text


def test_the_accounts_page_has_no_categories_and_the_categories_page_has_no_accounts(client, books):
    accounts = client.get("/accounts").text
    assert "Bank" in accounts and "Groceries" not in accounts and "Salary" not in accounts
    categories = client.get("/categories").text
    assert "Food" in categories and "Rent" in categories and "Bank" not in categories


def rows(page: str) -> list[tuple[str, str, str]]:
    """(name, hint, amount) of every row on the Categories page, in the order shown."""
    import re

    found = re.findall(
        r'<span class="crow-name">(.*?)</span>(?:<span class="crow-sub">(.*?)</span>)?</span>\s*<span class="crow-amt"><span class="[^"]*">(.*?)</span>(?:<span class="crow-share">(.*?)</span>)?',
        page, flags=re.S)
    dot = re.compile(r'<span class="cdot".*?</span>')  # the colour dot of the share bar is not part of the name
    return [(dot.sub("", name), hint, f"{amount} {share}".strip()) for name, hint, amount, share in found]


def test_categories_are_ranked_by_what_they_came_to_with_their_share_and_what_is_inside(client, books):
    entry(client, books["groceries"], books["bank"], "300", THIS_MONTH)
    entry(client, books["dining"], books["bank"], "200", THIS_MONTH)
    entry(client, books["rent"], books["bank"], "1000", THIS_MONTH)
    page = client.get("/categories").text
    assert "1,500.00" in page, "the month's spending"
    assert rows(page)[:2] == [("Rent", "", "1,000.00 67%"), ("Food", "Groceries · Dining", "500.00 33%")], "biggest first"
    assert "cgrp" not in page and "<details" not in page.split('data-categories')[1], "nothing folds"


def test_the_hint_names_the_three_biggest_and_counts_the_rest(client, books):
    for name, amount in (("A1", "50"), ("A2", "40"), ("A3", "30"), ("A4", "20")):
        made = client.post("/api/accounts/", json={"name": name, "parent_id": books["travel"]["aid"]}).json()
        entry(client, made, books["bank"], amount, THIS_MONTH)
    assert rows(client.get("/categories").text)[0] == ("Travel", "A1 · A2 · A3 · +1", "140.00 100%")


def test_a_small_share_says_less_than_one_percent(client, books):
    entry(client, books["rent"], books["bank"], "10000", THIS_MONTH)
    entry(client, books["travel"], books["bank"], "5", THIS_MONTH)
    assert ("Travel", "", "5.00 &lt;1%") in rows(client.get("/categories").text)


def test_money_posted_to_a_group_itself_is_its_everything_else_row(client, books):
    entry(client, books["food"], books["bank"], "40", THIS_MONTH)
    entry(client, books["groceries"], books["bank"], "60", THIS_MONTH)
    assert ("Food", "Groceries", "100.00 100%") in rows(client.get("/categories").text)
    page = client.get(f"/categories/{books['food']['aid']}").text
    assert "Sub-categories" in page and "Everything else" in page and "posted to Food itself" in page and "40.00" in page


def test_a_category_page_lists_its_sub_categories_biggest_first(client, books):
    entry(client, books["dining"], books["bank"], "200", THIS_MONTH)
    entry(client, books["groceries"], books["bank"], "300", THIS_MONTH)
    page = client.get(f"/categories/{books['food']['aid']}").text
    inside = page.split("Sub-categories")[1].split("Transactions")[0]
    assert inside.index("Groceries") < inside.index("Dining") and "Everything else" not in inside
    assert f"/categories/{books['groceries']['aid']}?month=" in inside
    assert "Sub-categories" not in client.get(f"/categories/{books['groceries']['aid']}").text, "nothing inside it"


def test_it_is_one_month_at_a_time_and_never_the_future(client, books):
    entry(client, books["rent"], books["bank"], "1000", LAST_MONTH.replace(day=5))
    this = client.get("/categories").text
    assert "1,000.00" not in this
    last = client.get(f"/categories?month={LAST_MONTH:%Y-%m}").text
    assert "1,000.00" in last and "Spent in" in last
    nxt = client.get(f"/categories?month={(THIS_MONTH + timedelta(days=40)):%Y-%m}", follow_redirects=False)
    assert nxt.status_code == 303 and "/categories" in nxt.headers["location"]


def test_income_is_its_own_tab_with_a_plus_free_green_list(client, books):
    entry(client, books["bank"], books["salary"], "5000", THIS_MONTH)
    page = client.get("/categories?tab=income").text
    assert '<span class="sr-only">Earned so far</span>' in page and "5,000.00" in page and "Salary" in page and "Rent" not in page
    assert 'aria-pressed="true">Income<' in page


def test_categories_with_nothing_this_month_are_tucked_away_once_something_has_something(client, books):
    assert "unused-hidden" not in client.get("/categories").text, "nothing yet: everything shows"
    entry(client, books["rent"], books["bank"], "1000", THIS_MONTH)
    page = client.get("/categories").text
    assert page.count('class="top unused-hidden"') == 2 and ">Load more</button>" in page and "with nothing in" not in page


def test_a_category_page_shows_its_month_and_its_transactions(client, books):
    entry(client, books["groceries"], books["bank"], "300", THIS_MONTH)
    entry(client, books["groceries"], books["bank"], "70", LAST_MONTH.replace(day=3))
    page = client.get(f"/categories/{books['groceries']['aid']}").text
    assert "300.00" in page and "Add transaction" in page and "/budget" in page
    assert page.count('class="tx"') == 1, "only this month's"
    assert "Add sub-category" not in page, "a sub-category is as deep as it gets"
    assert "Add sub-category" in client.get(f"/categories/{books['food']['aid']}").text


def test_an_account_page_for_a_category_goes_to_the_category_page(client, books):
    response = client.get(f"/accounts/{books['rent']['aid']}", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"/categories/{books['rent']['aid']}"
    assert client.get(f"/categories/{books['bank']['aid']}").status_code == 404, "an asset is not a category"


def test_adding_and_deleting_a_category_stay_on_the_categories_side(client, books):
    created = client.post("/accounts", data={"name": "Gifts", "parent_id": books["food"]["aid"]})
    assert created.status_code == 200
    gift = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Gifts")
    assert "Delete category" in client.get(f"/accounts/{gift['aid']}/edit").text
    deleted = client.post(f"/accounts/{gift['aid']}/delete")
    assert deleted.headers["HX-Redirect"] == "/categories"


def test_the_empty_page_invites_the_first_category(client, root_accounts):
    page = client.get("/categories").text
    assert "No expense categories yet" in page and 'href="/categories/new"' in page


def test_the_chips_are_expense_and_income_and_the_old_spelling_still_works(client, books):
    entry(client, books["rent"], books["bank"], "700", THIS_MONTH)
    page = client.get("/categories").text
    assert 'aria-pressed="true">Expense<' in page and ">Income<" in page and ">Spending<" not in page
    old = client.get("/categories?tab=spending").text
    assert 'aria-pressed="true">Expense<' in old and "700.00" in old


# ---- deleting a category -----------------------------------------------------------------------------------------------


def names(client):
    return {a["name"]: a for a in client.get("/api/accounts/").json()}


def test_an_unused_category_is_deleted_for_good(client, books):
    response = client.post(f"/accounts/{books['dining']['aid']}/delete")
    assert response.headers["HX-Redirect"] == "/categories" and "category-deleted" in response.headers["set-cookie"]
    assert "Dining" not in names(client)


def test_a_category_with_entries_leaves_the_lists_but_keeps_its_history(client, books):
    entry(client, books["groceries"], books["bank"], "300", LAST_MONTH.replace(day=3))
    response = client.post(f"/accounts/{books['groceries']['aid']}/delete")
    assert response.headers["HX-Redirect"] == "/categories" and "category-deleted" in response.headers["set-cookie"]
    assert names(client)["Groceries"]["closed_on"], "kept, so the old entry still has its category"
    this = client.get("/categories").text
    assert "Groceries" not in this, "not listed where it has nothing"
    assert "Groceries" in client.get(f"/categories?month={LAST_MONTH:%Y-%m}").text, "still in the month it was used"
    assert f'value="{books["groceries"]["aid"]}"' not in client.get("/transactions/new").text
    restored = client.post(f"/accounts/{books['groceries']['aid']}/reopen")
    assert "category-restored" in restored.headers["set-cookie"] and not names(client)["Groceries"]["closed_on"]


def test_a_category_with_sub_categories_takes_them_along(client, books):
    response = client.post(f"/accounts/{books['food']['aid']}/delete")
    assert response.headers["HX-Redirect"] == "/categories"
    after = names(client)
    assert after["Food"]["closed_on"] and after["Groceries"]["closed_on"] and after["Dining"]["closed_on"]
    assert "Food" not in client.get("/categories").text


def test_a_closed_sub_category_is_not_listed_under_its_group(client, books):
    entry(client, books["groceries"], books["bank"], "300", THIS_MONTH)
    client.post(f"/api/accounts/{books['dining']['aid']}/close")
    page = client.get(f"/categories/{books['food']['aid']}").text
    assert "Groceries" in page and "Dining" not in page.split("Sub-categories")[1].split("Transactions")[0]
    assert rows(client.get("/categories").text)[0] == ("Food", "Groceries", "300.00 100%")


def test_a_category_that_was_spent_in_can_be_deleted_without_emptying_it_first(client, books):
    entry(client, books["rent"], books["bank"], "900", THIS_MONTH)
    assert client.post(f"/api/accounts/{books['rent']['aid']}/close").status_code == 200, "its balance is spending, not money"
    assert client.post(f"/api/accounts/{books['bank']['aid']}/close").status_code == 400, "an account still holding money is not"


def test_a_category_page_says_delete_where_an_account_says_close(client, books):
    category = client.get(f"/categories/{books['rent']['aid']}").text
    assert "Delete category" in category and "Close account" not in category
    assert f"/accounts/{books['rent']['aid']}/delete" in category
    account_page = client.get(f"/accounts/{books['bank']['aid']}").text
    assert "Close account" in account_page and "Delete category" not in account_page
    form = client.get(f"/accounts/{books['rent']['aid']}/edit").text
    assert "removed for good" in form and "Delete category" in form


def test_the_figure_has_no_visible_label_only_one_for_screen_readers(client, books):
    entry(client, books["bank"], books["rent"], "40", THIS_MONTH)
    page = client.get("/categories").text
    hero = page.split('class="ready zero cat-hero"', 1)[1].split("</div>", 1)[0]
    assert '<span class="sr-only">Spent so far</span>' in hero and 'class="muted"' not in hero
    last = (THIS_MONTH - timedelta(days=1)).replace(day=1)
    entry(client, books["bank"], books["rent"], "60", last)
    past = client.get(f"/categories?month={last.strftime('%Y-%m')}").text
    assert f'<span class="sr-only">Spent in {last.strftime("%B")}</span>' in past and "so far" not in past


def test_the_page_ends_with_its_list_not_with_a_hint(client, books):
    entry(client, books["bank"], books["rent"], "40", THIS_MONTH)
    assert "Tap a category" not in client.get("/categories").text


def test_every_row_has_a_share_the_unused_ones_say_0_percent(client, books):
    entry(client, books["rent"], books["bank"], "1000", THIS_MONTH)
    page = client.get("/categories").text
    rows = page.split('data-cat-tree>', 1)[1].split("</main>", 1)[0].split('<div class="top')[1:]
    assert len(rows) == 3
    assert all('class="crow-share"' in row for row in rows), "no row is left without a share"
    used = [r for r in rows if "unused-hidden" not in r.split(">", 1)[0]]
    quiet = [r for r in rows if "unused-hidden" in r.split(">", 1)[0]]
    assert len(used) == 1 and ">100%<" in used[0] and all(">0%<" in r for r in quiet)


def test_with_nothing_in_the_month_every_row_reads_0_percent_and_still_has_one(client, books):
    page = client.get("/categories").text
    assert page.count('class="crow-share"') == page.count('class="r crow"') and ">0%<" in page


def test_share_rounding_edges():
    from decimal import Decimal

    from app.routers.web.categories import _share

    assert _share(Decimal(0), Decimal(100)) == "0%" and _share(Decimal(0), Decimal(0)) == "0%"
    assert _share(Decimal("0.4"), Decimal(100)) == "<1%" and _share(Decimal(25), Decimal(100)) == "25%"
    assert _share(Decimal(5), Decimal(0)) == "", "no total to take a share of"


# ---- the share bar -----------------------------------------------------------------------------------------


def bar_of(page: str):
    import re

    found = re.search(r'<div class="sharebar" role="img" aria-label="([^"]*)">(.*?)</div>', page, flags=re.S)
    if not found:
        return None
    segments = re.findall(r'flex-grow: ([\d.]+); background: var\(--chart-(\d)\)', found.group(2))
    return found.group(1), [(float(g), int(c)) for g, c in segments]


def test_the_share_bar_shows_the_biggest_five_and_one_grey_for_the_rest(client, books, root_accounts):
    more = [client.post("/api/accounts/", json={"name": f"More{i}", "parent_id": root_accounts["Expenses"]}).json() for i in range(3)]
    for i, category in enumerate([books["rent"], books["food"], books["travel"], *more]):  # six categories, 600 down to 100
        entry(client, category, books["bank"], str((6 - i) * 100), THIS_MONTH)
    page = client.get("/categories").text
    label, segments = bar_of(page)
    assert [c for _, c in segments] == [1, 2, 3, 4, 5, 6], "five colours, then the grey"
    assert abs(sum(g for g, _ in segments) - 100) < 0.1
    assert label.startswith("Share of the month: Rent 29%") and label.endswith("Everything else 5%")


def test_every_row_keeps_its_place_whether_it_has_a_colour_or_not(client, books):
    entry(client, books["rent"], books["bank"], "1000", THIS_MONTH)
    entry(client, books["groceries"], books["bank"], "500", THIS_MONTH)
    page = client.get("/categories").text
    assert page.count('class="cdot"') == page.count('class="r crow"') == 3, "an unused row has an invisible dot, so the names line up"
    assert page.split('data-cat-tree>', 1)[1].count('style="background: var(--chart-') == 2, "only the rows in the bar are coloured"


def test_no_bar_when_there_is_nothing_to_compare(client, books):
    assert bar_of(client.get("/categories").text) is None, "an empty month"
    entry(client, books["rent"], books["bank"], "1000", THIS_MONTH)
    page = client.get("/categories").text
    assert bar_of(page) is None and "cdot" not in page, "one category is the whole month: nothing to compare"


def test_no_bar_when_money_came_back_in_a_category(client, books):
    entry(client, books["rent"], books["bank"], "1000", THIS_MONTH)
    entry(client, books["bank"], books["travel"], "50", THIS_MONTH)  # a refund: money into the bank from a category
    entry(client, books["groceries"], books["bank"], "200", THIS_MONTH)
    assert bar_of(client.get("/categories").text) is None


def test_income_has_its_own_bar(client, books, root_accounts):
    other = client.post("/api/accounts/", json={"name": "Interest", "parent_id": root_accounts["Income"]}).json()
    entry(client, books["bank"], books["salary"], "9000", THIS_MONTH)
    entry(client, books["bank"], other, "1000", THIS_MONTH)
    label, segments = bar_of(client.get("/categories?tab=income").text)
    assert [c for _, c in segments] == [1, 2] and "Salary 90%" in label and "Interest 10%" in label
    assert bar_of(client.get("/categories").text) is None, "the expense tab has none of the income"
