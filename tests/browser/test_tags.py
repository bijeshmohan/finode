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
    note.fill("Capitals do not matter #GO")
    expect(pop.locator("button")).to_have_count(1)
    expect(pop.locator("button")).to_contain_text("#goa-trip")
    note.fill("no hash here")
    expect(pop).to_be_hidden()
    note.fill("a#b")  # a # inside a word is not a tag
    expect(pop).to_be_hidden()


def test_tapping_a_suggestion_with_a_finger_finishes_the_tag(touch_page: Page, books, api: Api):
    """On a phone the tap takes the focus from the note before the click arrives; the suggestion must still land."""
    add(api, books, "Taj", "Hotel #goa-trip", "840")
    touch_page.goto("/transactions/new")
    note = touch_page.get_by_label("Note")
    note.tap()
    note.press_sequentially("Dinner with Ravi #g")
    suggestion = touch_page.locator(".tag-pop button", has_text="#goa-trip")
    expect(suggestion).to_be_visible()
    suggestion.tap()
    expect(note).to_have_value("Dinner with Ravi #goa-trip ")
    expect(touch_page.locator(".tag-pop")).to_be_hidden()


def test_choosing_a_suggestion_does_not_press_what_is_under_it(touch_page: Page, books, api: Api):
    """The list covers the "Related transaction" row; the click that ends the tap must not reach that row."""
    add(api, books, "Taj", "Hotel #goa-trip", "840")
    touch_page.goto("/transactions/new")
    note = touch_page.get_by_label("Note")
    note.tap()
    note.press_sequentially("Dinner #g")
    suggestion = touch_page.locator(".tag-pop button", has_text="#goa-trip")
    related = touch_page.locator("[data-related-add]")
    expect(suggestion).to_be_visible()
    pop_box, related_box = suggestion.bounding_box(), related.bounding_box()
    assert pop_box["y"] + pop_box["height"] > related_box["y"], "the suggestion sits over the Related row"
    suggestion.tap()
    expect(note).to_have_value("Dinner #goa-trip ")
    touch_page.wait_for_timeout(700)  # long enough for a stray click to open the picker
    expect(touch_page.locator("#related-picker")).not_to_be_visible()
    expect(touch_page.locator("[data-related-chip]")).to_be_hidden()
    related.tap()  # a real tap on the Related row afterwards still works
    expect(touch_page.locator("#related-picker")).to_be_visible()


def test_a_mouse_click_on_a_suggestion_does_not_press_what_is_under_it(page: Page, books, api: Api):
    add(api, books, "Taj", "Hotel #goa-trip", "840")
    page.goto("/transactions/new")
    note = page.get_by_label("Note")
    note.fill("Dinner #g")
    page.locator(".tag-pop button", has_text="#goa-trip").click()
    expect(note).to_have_value("Dinner #goa-trip ")
    page.wait_for_timeout(500)
    expect(page.locator("#related-picker")).not_to_be_visible()
