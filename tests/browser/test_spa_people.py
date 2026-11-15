"""The React app's People pages in a browser (ports of test_people.py's People-page tests): a person's short-hands to
the Add screen, undoing an entry, the figures, what evens out by itself, and the rows and head beside the other pages'."""

import re

from playwright.sync_api import Page, expect

from .conftest import Api


def alice_of(api: Api, name: str = "Alice") -> dict:
    return api.post("/contacts/", name=name)


def lend(api: Api, books: dict, who: dict, amount: str = "500") -> dict:
    return api.post(
        f"/contacts/{who['id']}/transfers",
        direction="sent",
        purpose="loan",
        amount=amount,
        account_id=books["checking"]["id"],
    )


def side(page: Page, title: str):
    return page.locator("main").get_by_role("button", name=re.compile(f"^{title}"))


def choose(page: Page, title: str, label: str):
    side(page, title).click()
    page.get_by_role("dialog", name=title).get_by_role("button", name=re.compile(re.escape(label))).first.click()


def figure(page: Page):
    return page.get_by_test_id("person-figure")


def test_lend_from_a_persons_page(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    who = alice_of(spa_api)
    page.goto(f"/people/{who['id']}")
    expect(page.locator("main h1")).to_have_text("Alice")
    expect(page.get_by_text("All settled up")).to_be_visible()
    page.get_by_role("link", name="Lend", exact=True).click()
    page.wait_for_url("**/transactions/new**")
    page.get_by_label("Amount", exact=True).fill("500")
    expect(side(page, "To")).to_contain_text("Alice")  # the short-hand filled the person in
    choose(page, "From", "Checking")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.get_by_text("Alice owes you")).to_be_visible()
    expect(figure(page)).to_contain_text("500.00")
    checking = next(a for a in spa_api.get("/accounts/") if a["name"] == "Checking")
    assert float(checking["balance"]) == 4500


def test_settle_opens_the_add_screen_with_what_is_owed(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    who = alice_of(spa_api)
    lend(spa_api, spa_books, who)
    page.goto(f"/people/{who['id']}")
    page.get_by_role("link", name="Settle", exact=True).click()
    page.wait_for_url("**/transactions/new**")
    expect(page.get_by_label("Amount", exact=True)).to_have_value("500.00")
    expect(side(page, "From")).to_contain_text("Alice")  # they pay you back
    page.get_by_label("Amount", exact=True).fill("800")
    choose(page, "To", "Checking")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.get_by_text("You owe Alice")).to_be_visible()
    expect(figure(page)).to_contain_text("300.00")


def test_reversing_an_entry_asks_first(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    who = alice_of(spa_api)
    lend(spa_api, spa_books, who)
    page.goto(f"/people/{who['id']}")
    expect(figure(page)).to_contain_text("500.00")
    page.locator("main").get_by_role("button", name=re.compile("^Loan")).first.click()
    sheet = page.get_by_role("dialog", name="Loan")
    expect(sheet).to_be_visible()
    page.once("dialog", lambda dialog: dialog.dismiss())
    sheet.get_by_role("button", name="Reverse").click()
    expect(figure(page)).to_contain_text("500.00")  # declined: still there
    page.once("dialog", lambda dialog: dialog.accept())
    sheet.get_by_role("button", name="Reverse").click()
    expect(sheet).to_have_count(0)
    expect(page.get_by_text("All settled up")).to_be_visible()
    expect(page.get_by_text("Reversed. It is as if it never happened.")).to_be_visible()
    assert spa_api.get("/reports/trial-balance")["balanced"]


def test_a_reverse_refused_stays_in_the_sheet(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    who = alice_of(spa_api)
    lend(spa_api, spa_books, who, amount="50")
    spa_api.post(
        f"/contacts/{who['id']}/settlements",
        direction="received",
        amount="20",
        account_id=spa_books["checking"]["id"],
    )
    page.goto(f"/people/{who['id']}")
    page.locator("main").get_by_role("button", name=re.compile("^Loan")).first.click()
    sheet = page.get_by_role("dialog", name="Loan")
    page.once("dialog", lambda dialog: dialog.accept())
    sheet.get_by_role("button", name="Reverse").click()
    expect(sheet.get_by_role("alert")).to_contain_text("settle")
    expect(sheet).to_be_visible()


def test_the_figures_carry_the_rupee_sign_and_the_short_hands_sit_on_one_row(
    signed_in_spa_page: Page, spa_api: Api, spa_books
):
    page = signed_in_spa_page
    who = alice_of(spa_api)
    lend(spa_api, spa_books, who)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/people")
    expect(page.get_by_test_id("people-figure")).to_contain_text("₹")
    page.goto(f"/people/{who['id']}")
    expect(figure(page)).to_contain_text("₹")
    links = [page.get_by_role("link", name=n, exact=True) for n in ("Expense", "Lend", "Borrow", "Settle")]
    tops = {round(link.bounding_box()["y"]) for link in links}
    assert len(tops) == 1, "Expense, Lend, Borrow and Settle are on one row"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling"


def test_what_two_people_owe_each_other_evens_out_by_itself(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    who = alice_of(spa_api)
    checking = spa_books["checking"]["id"]
    lend(spa_api, spa_books, who, amount="23000")
    spa_api.post(
        f"/contacts/{who['id']}/transfers",
        direction="received",
        purpose="borrowing",
        amount="23000",
        account_id=checking,
    )
    page.goto("/people")
    row = page.locator("main").get_by_role("link", name=re.compile("^Alice"))
    expect(row).not_to_contain_text("each way")
    row.click()
    expect(page.get_by_text("All settled up")).to_be_visible()
    expect(page.locator("main")).to_contain_text("Evened out")


def test_the_rows_and_the_head_match_the_other_pages(signed_in_spa_page: Page, spa_api: Api, spa_books):
    """The People rows are the Categories rows; a person's head is an account's."""
    page = signed_in_spa_page
    who = alice_of(spa_api)
    lend(spa_api, spa_books, who)
    spa_api.post(
        "/transactions/",
        postings=[
            {
                "account_id": spa_books["roots"]["Expenses"],
                "category_id": spa_books["food"]["id"],
                "side": "debit",
                "amount": "40",
            },
            {"account_id": spa_books["checking"]["id"], "side": "credit", "amount": "40"},
        ],
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/people")
    person_row = page.locator("main").get_by_role("link", name=re.compile("^Alice")).bounding_box()
    page.goto("/categories")
    category_row = page.locator("main").get_by_role("link", name=re.compile("^Groceries")).bounding_box()
    assert person_row and category_row and abs(person_row["height"] - category_row["height"]) <= 2
    page.goto(f"/people/{who['id']}")
    size = figure(page).evaluate("e => getComputedStyle(e).fontSize")
    look = figure(page).get_attribute("class")
    page.goto(f"/accounts/{spa_books['checking']['id']}")
    balance = page.locator(f"main p.{look}")
    expect(balance).to_have_count(1)
    assert balance.evaluate("e => getComputedStyle(e).fontSize") == size


def test_add_a_person_from_the_empty_list(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/people")
    page.get_by_role("link", name="Add a person").click()
    page.get_by_label("Name").fill("Alice")
    page.get_by_role("button", name="Add person").click()
    page.wait_for_url(re.compile(r"/people/[0-9a-f-]{36}$"))
    expect(page.locator("main h1")).to_have_text("Alice")
    expect(page.get_by_text("All settled up")).to_be_visible()
    expect(page.get_by_text("Person added")).to_be_visible()


def test_a_new_person_can_start_with_an_opening_balance(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    page.goto("/people/new")
    page.get_by_label("Name").fill("Alice")
    page.get_by_role("button", name="Already owes you, or is owed?").click()
    page.get_by_label("Amount").fill("4000")
    page.get_by_role("button", name="Add person").click()
    page.wait_for_url(re.compile(r"/people/[0-9a-f-]{36}$"))
    expect(page.get_by_text("Alice owes you")).to_be_visible()
    expect(figure(page)).to_contain_text("4,000.00")
    expect(page.locator("main")).to_contain_text("Opening balance")
    page.get_by_label("More actions").click()
    page.get_by_role("link", name="Add an opening balance").click()
    page.get_by_text("You owe Alice").click()
    page.get_by_label("Amount").fill("1000")
    page.get_by_role("button", name="Add opening balance").click()
    page.wait_for_url(re.compile(r"/people/[0-9a-f-]{36}$"))
    expect(figure(page)).to_contain_text("3,000.00")
    assert float(next(a for a in spa_api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 5000


def test_a_bad_opening_amount_leaves_nobody_behind(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    page.goto("/people/new")
    page.get_by_label("Name").fill("Alice")
    page.get_by_role("button", name="Already owes you, or is owed?").click()
    page.get_by_label("Since").fill("1800-01-01")  # before the first day finode takes
    page.get_by_label("Amount").fill("40")
    page.get_by_role("button", name="Add person").click()
    expect(page.get_by_role("alert")).to_be_visible()
    expect(page).to_have_url(re.compile(r"/people/new$"))
    assert spa_api.get("/contacts/") == []


def test_an_opening_balance_can_be_edited_from_its_sheet(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    who = alice_of(spa_api)
    entry = spa_api.post(
        f"/contacts/{who['id']}/opening-balance", direction="receivable", amount="4000", date="2026-01-01"
    )
    page.goto(f"/people/{who['id']}")
    page.locator("main").get_by_role("button", name=re.compile("^Opening balance")).first.click()
    page.get_by_role("dialog", name="Opening balance").get_by_role("link", name="Edit").click()
    page.wait_for_url(f"**/opening/{entry['id']}/edit")
    expect(page.get_by_label("Amount")).to_have_value("4,000.00")
    page.get_by_label("Amount").fill("2500")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(figure(page)).to_contain_text("2,500.00")


def test_removing_someone_never_dealt_with_deletes_them_and_back_does_not_return(
    signed_in_spa_page: Page, spa_api: Api, spa_books
):
    page = signed_in_spa_page
    page.goto("/people")
    who = alice_of(spa_api, "Bob")
    page.goto(f"/people/{who['id']}")
    expect(page.locator("main h1")).to_have_text("Bob")
    page.get_by_label("More actions").click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Remove").click()
    page.wait_for_url(re.compile(r"/people$"))
    expect(page.get_by_text("Person removed")).to_be_visible()
    assert spa_api.get("/contacts/?include_archived=true") == []
    page.go_back()
    expect(page.locator("main h1")).not_to_have_text("Bob")
