"""Tags in a browser: chosen on the Add and Edit screens (chips and a sheet), the sheet's tag links, the Tag list in the
Filter sheet, and the Tags page."""

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def add(api: Api, books, payee, note, amount="100", target="food", tags=None):
    return api.post(
        "/transactions/",
        payee=payee,
        comment=note,
        tags=tags or [],
        postings=[
            leg(books[target], "debit", amount),
            leg(books["checking"], "credit", amount),
        ],
    )


def fill_and_save(page: Page, payee: str):
    page.fill("#total", "40")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', label="Groceries")
    page.fill('input[name="payee"]', payee)
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")


def test_tapping_a_tag_in_the_sheet_filters_the_list(page: Page, books, api: Api):
    add(api, books, "Taj", "Hotel", "840", tags=["goa-trip"])
    add(api, books, "Cab", "Airport", "160", tags=["goa-trip", "reimbursable"])
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
    add(api, books, "Taj", "Hotel", "840", tags=["goa-trip"])
    add(api, books, "Cab", "Airport", "160", tags=["goa-trip", "reimbursable"])
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


def test_choosing_tags_on_the_add_screen(page: Page, books, api: Api):
    add(api, books, "Taj", "Hotel", "840", tags=["goa-trip"])
    add(api, books, "Cab", "Airport", "160", tags=["goa-trip", "gifts"])
    page.goto("/transactions/new")
    expect(page.locator("[data-tags-chips] [data-tag]")).to_have_count(0)
    page.locator(".hash-btn").click()
    sheet = page.locator("#tags-picker")
    expect(sheet).to_be_visible()
    options = sheet.locator("[data-tag-option]")
    expect(options.first).to_contain_text("goa-trip")  # the more used one first
    options.filter(has_text="gifts").click()
    expect(options.filter(has_text="gifts")).to_have_attribute("aria-pressed", "true")
    sheet.locator("[data-tags-search]").fill("Brand-New")  # a word that is no tag yet: capitals do not matter
    expect(options.filter(has_text="goa-trip")).to_be_hidden()
    sheet.get_by_role("button", name="＋ Create “#brand-new”").click()
    expect(options.filter(has_text="brand-new")).to_have_attribute("aria-pressed", "true")
    sheet.locator("[data-tags-search]").fill("")
    options.filter(has_text="gifts").click()  # tapping a ticked tag takes it off again
    expect(options.filter(has_text="gifts")).to_have_attribute("aria-pressed", "false")
    sheet.locator("[data-tags-done]").click()
    expect(sheet).to_be_hidden()
    chips = page.locator("[data-tags-chips] [data-tag]")
    expect(chips).to_have_count(1)
    expect(chips.first).to_have_text("#brand-new")
    page.locator("[data-tags-chips]").click()  # the line of tags opens the sheet too
    options.filter(has_text="goa-trip").click()
    options.filter(has_text="brand-new").click()
    sheet.locator("[data-tags-done]").click()
    expect(chips).to_have_count(1)
    expect(chips.first).to_have_text("#goa-trip")
    fill_and_save(page, "Resort")
    [entry] = [t for t in api.get("/transactions/") if t["payee"] == "Resort"]
    assert entry["tags"] == ["goa-trip"] and entry["comment"] is None


def test_a_note_with_a_hash_stays_a_note(page: Page, books, api: Api):
    page.goto("/transactions/new")
    page.get_by_label("Note").fill("Issue #3 and #goa-trip")
    expect(page.locator(".tag-pop")).to_have_count(0)
    fill_and_save(page, "Words")
    [entry] = [t for t in api.get("/transactions/") if t["payee"] == "Words"]
    assert entry["tags"] == [] and entry["comment"] == "Issue #3 and #goa-trip"


def test_editing_an_entry_shows_its_tags_and_saves_the_changes(page: Page, books, api: Api):
    made = add(api, books, "Taj", "Hotel", "840", tags=["goa-trip", "work"])
    page.goto(f"/transactions/{made['tid']}/edit")
    chips = page.locator("[data-tags-chips] [data-tag]")
    expect(chips).to_have_count(2)
    page.locator(".hash-btn").click()
    page.locator("#tags-picker [data-tag-option]", has_text="work").click()
    page.locator("#tags-picker [data-tags-done]").click()
    expect(chips).to_have_count(1)
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url("**/transactions")
    assert api.get(f"/transactions/{made['tid']}")["tags"] == ["goa-trip"]


def test_tapping_a_tag_with_a_finger(touch_page: Page, books, api: Api):
    add(api, books, "Taj", "Hotel", "840", tags=["goa-trip"])
    touch_page.goto("/transactions/new")
    touch_page.locator(".hash-btn").tap()
    option = touch_page.locator("#tags-picker [data-tag-option]", has_text="goa-trip")
    expect(option).to_be_visible()
    option.tap()
    touch_page.locator("#tags-picker [data-tags-done]").tap()
    expect(touch_page.locator("[data-tags-chips] [data-tag]")).to_have_count(1)
    expect(touch_page.locator("#related-picker")).not_to_be_visible()


def test_the_tags_page_renames_merges_and_deletes(page: Page, books, api: Api):
    add(api, books, "A", "n", tags=["alpha"])
    add(api, books, "B", "n", tags=["beta"])
    page.goto("/settings")
    page.get_by_role("link", name="Tags").click()
    page.wait_for_url("**/tags")
    expect(page.locator(".tag-row")).to_have_count(2)
    page.locator(".tag-row", has_text="alpha").click()
    sheet = page.locator("#tag-sheet")
    expect(sheet).to_be_visible()
    expect(sheet.get_by_role("link", name="View entries")).to_be_visible()
    sheet.locator("summary", has_text="Rename").click()
    sheet.get_by_label("New name").fill("not valid")
    sheet.get_by_role("button", name="Rename").click()
    expect(sheet.locator("#tag-sheet-error")).to_contain_text("cannot be a tag")
    sheet.get_by_label("New name").fill("Holiday")
    sheet.get_by_role("button", name="Rename").click()
    page.wait_for_url("**/tags")
    expect(page.locator(".tag-row", has_text="holiday")).to_be_visible()
    page.locator(".tag-row", has_text="holiday").click()
    sheet.locator("summary", has_text="Merge into").click()
    sheet.locator("select[name=into]").select_option("beta")
    sheet.get_by_role("button", name="Merge").click()
    expect(page.locator(".tag-row")).to_have_count(1)
    page.once("dialog", lambda dialog: dialog.accept())  # the confirmation
    page.locator(".tag-row").click()
    sheet.get_by_role("button", name="Delete tag").click()
    expect(page.get_by_text("No tags yet")).to_be_visible()
    assert api.get("/tags/") == []


def test_a_new_tag_is_made_on_the_fly_and_saved_with_the_entry(touch_page: Page, books, api: Api):
    page = touch_page
    add(api, books, "Taj", "Hotel", "840", tags=["goa-trip"])
    page.goto("/transactions/new")
    page.locator(".hash-btn").tap()
    sheet = page.locator("#tags-picker")
    expect(sheet.locator("[data-tag-option]")).to_have_count(1)  # the list has arrived
    search = sheet.locator("[data-tags-search]")
    search.fill("Fresh Idea")  # a space is turned into a hyphen, capitals into lower case
    sheet.get_by_role("button", name="＋ Create “#fresh-idea”").tap()
    expect(sheet.locator("[data-tag-option]", has_text="fresh-idea")).to_have_attribute("aria-pressed", "true")
    search.fill("a*b")  # what cannot be a tag says so instead of offering nothing
    expect(sheet.locator("[data-tag-create]")).to_contain_text("letters, digits")
    search.fill("")
    sheet.locator("[data-tags-done]").tap()
    expect(page.locator("[data-tags-chips] [data-tag]")).to_have_text(["#fresh-idea"])
    fill_and_save(page, "Resort")
    [entry] = [t for t in api.get("/transactions/") if t["payee"] == "Resort"]
    assert entry["tags"] == ["fresh-idea"]
    assert [t["tag"] for t in api.get("/tags/")].count("fresh-idea") == 1


def test_a_finger_that_lifts_chooses_even_when_the_click_never_arrives(touch_page: Page, books, api: Api):
    """With the keyboard open the sheet moves under the finger and the browser drops the click: the lift must choose."""
    page = touch_page
    add(api, books, "Taj", "Hotel", "840", tags=["goa-trip"])
    page.goto("/transactions/new")
    page.locator(".hash-btn").tap()
    sheet = page.locator("#tags-picker")
    option = sheet.locator("[data-tag-option]", has_text="goa-trip")
    expect(option).to_be_visible()
    option.evaluate(
        """el => {
            const at = {pointerType: "touch", bubbles: true, clientX: 50, clientY: 50};
            el.dispatchEvent(new PointerEvent("pointerdown", at));
            el.dispatchEvent(new PointerEvent("pointerup", at));
        }"""
    )  # no click follows
    expect(option).to_have_attribute("aria-pressed", "true")
    option.evaluate("el => el.click()")  # a click that does follow is the same tap, not a second one
    expect(option).to_have_attribute("aria-pressed", "true")


def test_opening_the_tags_sheet_on_a_phone_does_not_open_the_keyboard(touch_page: Page, books, api: Api):
    add(api, books, "Taj", "Hotel", "840", tags=["goa-trip"])
    touch_page.goto("/transactions/new")
    touch_page.locator(".hash-btn").tap()
    expect(touch_page.locator("#tags-picker")).to_be_visible()
    expect(touch_page.locator("[data-tags-search]")).not_to_be_focused()
    touch_page.locator("[data-tags-search]").tap()
    expect(touch_page.locator("[data-tags-search]")).to_be_focused()  # tapping the field is what opens it


def test_the_tags_page_rows_are_plain_rows_inside_one_tile(touch_page: Page, books, api: Api):
    """On a phone the rows must not take the global button look (dark pills side by side): one line each, full width."""
    add(api, books, "A", "n", tags=["alpha"])
    add(api, books, "B", "n", tags=["beta"])
    touch_page.goto("/tags")
    rows = touch_page.locator(".tag-row")
    expect(rows).to_have_count(2)
    first, second = rows.nth(0).bounding_box(), rows.nth(1).bounding_box()
    assert first and second and first["width"] > 300 and second["y"] > first["y"] + 40, "stacked, full width"
    assert rows.nth(0).evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
    count = rows.nth(0).locator(".tag-count").bounding_box()
    assert count and count["x"] + count["width"] > first["x"] + first["width"] - 20, "the count sits at the right"
