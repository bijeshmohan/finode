"""People in a real browser: adding someone, lending, sharing a bill with the live result, settling up and undoing."""

from playwright.sync_api import Page, expect

from .conftest import Api


def alice_of(api: Api, name: str = "Alice") -> dict:
    return api.post("/contacts/", name=name)


def test_add_a_person_and_lend_them_money(page: Page, books, api: Api):
    page.goto("/people")
    page.get_by_role("link", name="Add a person").click()
    page.locator('input[name="name"]').fill("Alice")
    page.get_by_role("button", name="Add person").click()
    page.wait_for_url("**/people/*")
    expect(page.locator("h1")).to_have_text("Alice")
    expect(page.get_by_text("All settled up")).to_be_visible()
    page.get_by_role("link", name="Lend or borrow").click()
    page.locator('input[name="amount"]').fill("500")
    page.locator(".field-pick").first.click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").first.click()
    expect(page.locator(".field-pick").first).to_have_text("Checking")
    page.get_by_role("button", name="Record").click()
    page.wait_for_url("**/people/*")
    expect(page.get_by_text("Alice owes you")).to_be_visible()
    expect(page.locator(".hero-balance")).to_contain_text("500.00")
    assert api.get("/accounts/")  # the books moved: the loan left Checking
    assert float(next(a for a in api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 4500


def test_a_gift_asks_for_a_category_only_when_it_is_a_gift(page: Page, books, api: Api):
    who = alice_of(api)
    page.goto(f"/people/{who['id']}/transfer")
    expect(page.locator('[data-gift="sent"]')).to_be_hidden()
    page.get_by_text("I gave a gift").click()
    expect(page.locator('[data-gift="sent"]')).to_be_visible()
    expect(page.locator('[data-gift="received"]')).to_be_hidden()
    page.get_by_text("They gave me a gift").click()
    expect(page.locator('[data-gift="received"]')).to_be_visible()
    page.get_by_text("I lent money").click()
    expect(page.locator('[data-gift="received"]')).to_be_hidden()


def test_sharing_a_bill_shows_the_result_as_you_type(page: Page, books, api: Api):
    who = alice_of(api)
    page.goto(f"/people/expense/new?with={who['id']}")
    expect(page.locator(f'input[name="with_{who["id"]}"]')).to_be_checked()
    page.locator('input[name="total_amount"]').fill("900")
    page.locator('input[name="description"]').fill("Dinner")
    page.locator(".field-pick").nth(1).click()  # the account (the category comes first)
    page.locator("#row-picker [data-pick-option]", has_text="Checking").first.click()
    preview = page.locator("#expense-preview")
    expect(preview).to_contain_text("Alice owes you")
    expect(preview).to_contain_text("450.00")
    page.get_by_text("%", exact=True).click()
    expect(page.locator(f'input[name="value_{who["id"]}"]')).to_be_visible()
    page.locator('input[name="value_self"]').fill("75")
    page.locator(f'input[name="value_{who["id"]}"]').fill("25")
    expect(preview).to_contain_text("225.00")
    page.get_by_role("button", name="Record expense").click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.locator(".hero-balance")).to_contain_text("225.00")


def test_settling_up_shows_what_it_clears_and_asks_about_the_rest(page: Page, books, api: Api):
    who = alice_of(api)
    checking = books["checking"]["id"]
    api.post(
        f"/contacts/{who['id']}/transfers",
        direction="sent",
        purpose="loan",
        amount="500",
        account_id=checking,
        description="Rent help",
    )
    page.goto(f"/people/{who['id']}/settle")
    page.locator(".field-pick").first.click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").first.click()
    page.locator('input[name="amount"]').fill("200")
    expect(page.locator("#settle-preview")).to_contain_text("Rent help")
    expect(page.locator("#settle-preview")).to_contain_text("300.00 left")
    page.locator('input[name="amount"]').fill("800")
    expect(page.locator("#settle-preview")).to_contain_text("is more than is owed")
    page.get_by_role("button", name="Settle up").click()
    expect(page.locator("#form-error")).to_contain_text("say what the rest is")
    page.get_by_text("A gift").click()
    page.get_by_role("button", name="Settle up").click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.get_by_text("All settled up")).to_be_visible()


def test_reversing_an_entry_asks_first(page: Page, books, api: Api):
    who = alice_of(api)
    api.post(
        f"/contacts/{who['id']}/transfers",
        direction="sent",
        purpose="loan",
        amount="500",
        account_id=books["checking"]["id"],
    )
    page.goto(f"/people/{who['id']}")
    expect(page.locator(".hero-balance")).to_contain_text("500.00")
    page.locator("a.person-entry").first.click()
    sheet = page.locator("#person-sheet")
    expect(sheet).to_be_visible()
    expect(sheet).to_contain_text("Loan")
    page.once("dialog", lambda dialog: dialog.dismiss())
    sheet.get_by_role("button", name="Reverse").click()
    expect(page.locator(".hero-balance")).to_contain_text("500.00")  # declined: still there
    page.once("dialog", lambda dialog: dialog.accept())
    sheet.get_by_role("button", name="Reverse").click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.get_by_text("All settled up")).to_be_visible()
