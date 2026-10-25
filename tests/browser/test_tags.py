"""Tags in a browser: the sheet's tag links, the Tag list in the Filter sheet, and the suggestions after a # on the Add screen."""

from playwright.sync_api import Page, expect

from .conftest import Api


def add(api: Api, books, payee, note, amount="100", target="food"):
    return api.post(
        "/transactions/",
        payee=payee,
        comment=note,
        postings=[
            {"account": books[target]["aid"], "side": "debit", "amount": amount},
            {"account": books["checking"]["aid"], "side": "credit", "amount": amount},
        ],
    )


def test_tapping_a_tag_in_the_sheet_filters_the_list(page: Page, books, api: Api):
    add(api, books, "Taj", "Hotel #goa-trip", "840")
    add(api, books, "Cab", "Airport #goa-trip #reimbursable", "160")
    add(api, books, "DMart", "weekly shop", "300")
    page.goto("/transactions")
    page.locator("a.tx", has_text="Taj").click()
    sheet = page.locator("#txn-sheet")
    expect(sheet.locator(".sheet-tags a", has_text="#goa-trip")).to_be_visible()
    sheet.locator(".sheet-tags a", has_text="#goa-trip").click()
    expect(page.locator("a.tx")).to_have_count(2)
    expect(page.locator(".tx-summary")).to_contain_text("2 transactions")
    expect(page.locator(".tx-summary")).to_contain_text("1,000.00 spent")
    expect(page.locator(".tx-applied")).to_contain_text("#goa-trip")
    page.locator(".tx-applied a").click()  # the ✕
    expect(page.locator("a.tx", has_text="DMart")).to_be_visible()  # back to everything, the untagged entry too


def test_the_filter_sheet_loads_the_tags_when_its_list_is_opened(page: Page, books, api: Api):
    add(api, books, "Taj", "Hotel #goa-trip", "840")
    add(api, books, "Cab", "Airport #goa-trip #reimbursable", "160")
    page.goto("/transactions")
    page.locator("[data-open-filter]").click()
    expect(page.locator("#tx-filter")).to_be_visible()
    page.locator('[data-pick="tag"]').click()
    options = page.locator('[data-filter-list="tag"] .filter-options button')
    expect(options.filter(has_text="#goa-trip")).to_contain_text("2 entries")
    expect(options.filter(has_text="#goa-trip")).to_contain_text("1,000.00")
    expect(options.filter(has_text="#reimbursable")).to_contain_text("1 entry")
    page.locator('[data-filter-list="tag"] [data-filter-search]').fill("reimb")
    expect(options.filter(has_text="#goa-trip")).to_be_hidden()
    options.filter(has_text="#reimbursable").click()
    expect(page.locator('[data-filter-label="tag"]')).to_have_text("#reimbursable")
    page.get_by_role("button", name="Show transactions").click()
    expect(page.locator("a.tx")).to_have_count(1)
    expect(page.locator("a.tx")).to_contain_text("Cab")
    assert "tag=reimbursable" in page.url


def test_typing_a_hash_in_the_note_offers_the_tags_in_use(page: Page, books, api: Api):
    add(api, books, "Taj", "Hotel #goa-trip", "840")
    add(api, books, "Cab", "Airport #goa-trip #gifts", "160")
    page.goto("/transactions/new")
    note = page.get_by_label("Note")
    pop = page.locator(".tag-pop")
    expect(pop).to_be_hidden()
    note.fill("Dinner with Ravi #g")
    expect(pop.locator("button")).to_have_count(2)
    expect(pop.locator("button").first).to_contain_text("#goa-trip")  # the more used one first
    pop.locator("button", has_text="#gifts").click()
    expect(note).to_have_value("Dinner with Ravi #gifts ")
    expect(pop).to_be_hidden()
    note.press_sequentially("and #")
    expect(pop.locator("button")).to_have_count(
        2
    )  # goa-trip and the one left, gifts is already there but still offered
    note.press("Escape")
    expect(pop).to_be_hidden()
    note.fill("no hash here")
    expect(pop).to_be_hidden()
    note.fill("a#b")  # a # inside a word is not a tag
    expect(pop).to_be_hidden()
