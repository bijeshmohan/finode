"""Tags in the web app: chosen on the Add and Edit screens, shown apart from the note on rows and in the sheet, found
through the Filter sheet, and looked after on the Tags page (Settings > Your data)."""

import re
from datetime import date

import pytest

from .htmlutil import text_of

TODAY = date.today()
MONTH = TODAY.strftime("%Y-%m")


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        return client.post("/api/accounts/", json={"name": name, "parent_id": root_accounts[root], **extra}).json()

    return {
        "bank": make("Bank", "Assets", balance="100000"),
        "travel": make("Travel", "Expenses"),
        "food": make("Food", "Expenses"),
        "salary": make("Salary", "Income"),
    }


def spend(client, books, amount, note=None, payee=None, to="travel", on=None, tags=None):
    body = {
        "date": str(on or TODAY),
        "payee": payee,
        "comment": note,
        "tags": tags or [],
        "postings": [
            {"account": books[to]["aid"], "side": "debit", "amount": amount},
            {"account": books["bank"]["aid"], "side": "credit", "amount": amount},
        ],
    }
    made = client.post("/api/transactions/", json=body)
    assert made.status_code == 201, made.text
    return made.json()


def earn(client, books, amount, tags):
    made = client.post(
        "/api/transactions/",
        json={
            "date": str(TODAY),
            "tags": tags,
            "postings": [
                {"account": books["bank"]["aid"], "side": "debit", "amount": amount},
                {"account": books["salary"]["aid"], "side": "credit", "amount": amount},
            ],
        },
    )
    assert made.status_code == 201, made.text
    return made.json()


def titles(page: str) -> list[str]:
    return re.findall(r'<span class="tx-title">([^<]*)</span>', page)


def form_fields(**extra):
    return {"date": str(TODAY), "payee": "", "comment": "", **extra}


# ---- rows and the sheet ---------------------------------------------------------------------------------------------


def test_a_row_shows_the_whole_note_and_no_tags(client, books):
    spend(client, books, "840", note="Dinner with Ravi", payee="Taj", tags=["goa-trip", "reimbursable"])
    page = client.get("/transactions").text
    assert "Dinner with Ravi" in page
    assert (
        "#goa-trip" not in page and "#reimbursable" not in page
    )  # tags are in the details sheet and the form, not in rows


def test_a_hash_in_a_note_is_only_text_on_a_row(client, books):
    spend(client, books, "10", note="Issue #1 and #goa-trip are words", payee="Words")
    page = client.get("/transactions").text
    assert "Issue #1 and #goa-trip are words" in page


def test_the_sheet_has_a_tags_row_that_filters_and_the_note_whole(client, books):
    made = spend(client, books, "840", note="Airport drop", payee="Cab", tags=["goa-trip", "reimbursable"])
    sheet = client.get(f"/transactions/{made['tid']}/sheet").text
    assert f'href="/transactions?month={MONTH}&amp;tag=goa-trip">#goa-trip</a>' in sheet
    assert "#reimbursable</a>" in sheet
    note = re.search(r"<dt>Note</dt><dd>([^<]*)</dd>", sheet)
    assert note and note.group(1) == "Airport drop"
    only = spend(client, books, "5", payee="Tag only", tags=["goa-trip"])
    assert "<dt>Note</dt>" not in client.get(f"/transactions/{only['tid']}/sheet").text, "no empty note row"
    none = spend(client, books, "5", note="just words", payee="No tags")
    assert "<dt>Tags</dt>" not in client.get(f"/transactions/{none['tid']}/sheet").text


# ---- finding the entries --------------------------------------------------------------------------------------------


def test_the_tag_filter_lists_only_those_entries_and_says_what_they_come_to(client, books):
    spend(client, books, "840", payee="Taj", tags=["goa-trip"])
    spend(client, books, "160", payee="Cab", tags=["Goa-Trip"])
    spend(client, books, "999", payee="Other", tags=["goa-tripping"])
    spend(client, books, "50", payee="Plain")
    page = client.get("/transactions", params={"tag": "goa-trip"}).text
    assert sorted(titles(page)) == ["Cab", "Taj"], "capitals do not matter and a longer tag is another tag"
    body = text_of(page)
    assert "2 transactions" in body and "1,000.00 spent" in body
    assert "#goa-trip" in page and "Remove the tag filter" in page
    assert 'name="tag"' in page and 'data-filter-value="tag"' in page
    assert titles(client.get("/transactions", params={"tag": "#GOA-trip"}).text) == titles(page)
    assert titles(client.get("/transactions", params={"tag": "nothing-here"}).text) == []


def test_the_tag_filter_combines_with_the_others_and_travels_with_show_more(client, books):
    for i in range(30):  # one a day, so no day has to be kept whole
        spend(
            client,
            books,
            "1",
            payee=f"P{i:02d}",
            to="food" if i % 2 else "travel",
            on=date(2026, 1, 1 + i),
            tags=["bulk"],
        )
    window = {"tag": "bulk", "date_from": "2026-01-01", "date_to": "2026-02-28"}
    first = client.get("/transactions", params=window).text
    assert len(titles(first)) == 25 and "Show 5 more" in first
    more = re.search(r'hx-get="(/transactions/more\?[^"]+)"', first).group(1).replace("&amp;", "&")
    assert "tag=bulk" in more
    assert len(titles(client.get(more).text)) == 5
    both = client.get("/transactions", params={**window, "category": books["food"]["aid"]}).text
    assert len(titles(both)) == 15


# ---- the lists the sheets use -----------------------------------------------------------------------------------------


def test_the_filter_list_has_uses_last_day_and_the_total_when_they_all_go_one_way(client, books):
    spend(client, books, "840", payee="A", tags=["goa-trip"])
    spend(client, books, "160", payee="B", tags=["goa-trip", "reimbursable"])
    earn(client, books, "500", ["reimbursable"])
    html = client.get("/transactions/tag-options").text
    trip = re.search(r'data-value="goa-trip".*?</button>', html, re.S).group(0)
    assert "2 entries" in trip and "1,000.00" in trip and TODAY.strftime("%d %b") in trip
    mixed = re.search(r'data-value="reimbursable".*?</button>', html, re.S).group(0)
    assert "2 entries" in mixed and "00" not in re.sub(r"<small.*?</small>", "", mixed), "spending and income: no total"


def test_the_filter_list_says_so_when_there_are_no_tags(client, books):
    spend(client, books, "5", note="words only", payee="X")
    assert "No tags yet" in client.get("/transactions/tag-options").text


def test_the_filter_sheet_has_a_tag_row_that_loads_its_list_when_opened(client, books):
    spend(client, books, "5", payee="X", tags=["goa-trip"])
    page = client.get("/transactions").text
    assert (
        'data-pick="tag"' in page
        and 'hx-get="/transactions/tag-options"' in page
        and 'hx-trigger="tags-open once"' in page
    )
    assert 'data-value="goa-trip"' not in page, "the tags are not read until the list is opened"


def test_the_tag_picker_lists_the_tags_most_used_first(client, books):
    spend(client, books, "1", payee="1", tags=["b"])
    spend(client, books, "1", payee="2", tags=["a", "b"])
    spend(client, books, "1", payee="3", tags=["a", "b", "c"])
    html = client.get("/transactions/tag-picker").text
    assert re.findall(r'data-tag-option="([^"]+)"', html) == ["b", "a", "c"]
    assert "3 entries" in html and "1 entry" in html


# ---- the Add and Edit screens ---------------------------------------------------------------------------------------


def test_the_add_screen_has_the_tags_row_and_the_sheet(client, books):
    page = client.get("/transactions/new").text
    assert "data-tags-open" in page and 'id="tags-picker"' in page and 'hx-get="/transactions/tag-picker"' in page
    assert "data-tag-note" not in page and "tag-pop" not in page, "no # suggestions any more: tags are not in the note"
    assert 'name="tags"' not in page


def test_saving_an_entry_sends_its_tags_and_the_edit_screen_shows_them(client, books):
    made = client.post(
        "/transactions/split",
        data=form_fields(
            account=[books["travel"]["aid"], books["bank"]["aid"]],
            side=["debit", "credit"],
            amount=["50", "50"],
            comment="Taxi from the airport",
            tags=["Goa-Trip", "reimbursable"],
        ),
    )
    assert made.status_code == 200, made.text
    entry = client.get("/api/transactions/").json()[0]
    assert entry["tags"] == ["goa-trip", "reimbursable"] and entry["comment"] == "Taxi from the airport"
    edit = client.get(f"/transactions/{entry['tid']}/edit").text
    assert edit.count('<input type="hidden" name="tags"') == 2
    assert 'data-tag="goa-trip"' in edit and 'data-tag="reimbursable"' in edit
    changed = client.post(
        f"/transactions/{entry['tid']}/edit",
        data=form_fields(
            account=[books["travel"]["aid"], books["bank"]["aid"]],
            side=["debit", "credit"],
            amount=["50", "50"],
            tags=["reimbursable"],
        ),
    )
    assert changed.status_code == 200
    assert client.get(f"/api/transactions/{entry['tid']}").json()["tags"] == ["reimbursable"]
    cleared = client.post(
        f"/transactions/{entry['tid']}/edit",
        data=form_fields(
            account=[books["travel"]["aid"], books["bank"]["aid"]], side=["debit", "credit"], amount=["50", "50"]
        ),
    )
    assert cleared.status_code == 200 and client.get(f"/api/transactions/{entry['tid']}").json()["tags"] == []


def test_a_bad_tag_on_the_form_says_why(client, books):
    refused = client.post(
        "/transactions/split",
        data=form_fields(
            account=[books["travel"]["aid"], books["bank"]["aid"]],
            side=["debit", "credit"],
            amount=["5", "5"],
            tags=["not valid"],
        ),
    )
    assert (
        refused.status_code == 400
        and refused.headers["HX-Retarget"] == "#form-error"
        and "cannot be a tag" in refused.text
    )


def test_repeating_an_entry_copies_its_tags(client, books):
    made = spend(client, books, "30", payee="Cab", tags=["work"])
    page = client.get("/transactions/new", params={"repeat": made["tid"]}).text
    assert 'data-tag="work"' in page and 'name="tags" value="work"' in page


# ---- the Tags page -------------------------------------------------------------------------------------------------


def test_the_settings_page_links_to_tags(client):
    assert 'href="/tags"' in client.get("/settings").text


def test_the_tags_page_lists_the_tags(client, books):
    assert "No tags yet" in client.get("/tags").text
    spend(client, books, "5", payee="A", tags=["goa-trip"])
    spend(client, books, "5", payee="B", tags=["goa-trip", "work"])
    page = client.get("/tags").text
    assert page.index("goa-trip") < page.index("work")
    assert '<span class="tag-count">2</span>' in page and '<span class="tag-count">1</span>' in page
    assert 'hx-get="/tags/goa-trip/sheet"' in page
    assert "1 entry" in client.get("/tags/work/sheet").text


def test_a_tags_sheet_has_rename_merge_and_delete(client, books):
    spend(client, books, "5", payee="A", tags=["goa-trip"])
    spend(client, books, "5", payee="B", tags=["work"])
    sheet = client.get("/tags/goa-trip/sheet").text
    assert 'hx-post="/tags/goa-trip/rename"' in sheet and 'hx-post="/tags/goa-trip/merge"' in sheet
    assert '<option value="work">' in sheet and 'hx-post="/tags/goa-trip/delete"' in sheet
    assert "tag=goa-trip" in sheet
    alone = client.get("/tags/work/sheet").text
    assert 'hx-post="/tags/work/merge"' in alone and '<option value="goa-trip">' in alone
    assert client.get("/tags/nothing/sheet").status_code == 404


def test_renaming_merging_and_deleting_from_the_tags_page(client, books):
    spend(client, books, "5", payee="A", tags=["trip"])
    spend(client, books, "5", payee="B", tags=["goa-trip"])
    renamed = client.post("/tags/trip/rename", data={"to": "Holiday"})
    assert (
        renamed.status_code == 200
        and renamed.headers["HX-Redirect"] == "/tags"
        and "tag-renamed" in renamed.headers["set-cookie"]
    )
    assert sorted(t["tag"] for t in client.get("/api/tags/").json()) == ["goa-trip", "holiday"]
    bad = client.post("/tags/holiday/rename", data={"to": "not valid"})
    assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#tag-sheet-error"
    merged = client.post("/tags/holiday/merge", data={"into": "goa-trip"})
    assert merged.status_code == 200 and "tag-merged" in merged.headers["set-cookie"]
    assert [t["tag"] for t in client.get("/api/tags/").json()] == ["goa-trip"]
    gone = client.post("/tags/goa-trip/delete")
    assert gone.status_code == 200 and "tag-deleted" in gone.headers["set-cookie"]
    assert client.get("/api/tags/").json() == []
    assert client.post("/tags/goa-trip/delete").status_code == 404


def test_tags_are_case_insensitive_everywhere(client, books):
    spend(client, books, "100", payee="A", tags=["emi"])
    spend(client, books, "200", payee="B", tags=["EMI"])
    spend(client, books, "300", payee="C", tags=["Emi"])
    assert client.get("/api/tags/").json()[0]["uses"] == 3 and len(client.get("/api/tags/").json()) == 1
    options = client.get("/transactions/tag-options").text
    assert options.count('data-value="') == 1 and "3 entries" in options and "600.00" in options
    for spelling in ("emi", "EMI", "#Emi", " #eMI "):
        assert sorted(titles(client.get("/transactions", params={"tag": spelling}).text)) == ["A", "B", "C"], spelling
    page = client.get("/transactions").text
    assert "#EMI" not in page and "#Emi" not in page


def test_an_entry_you_made_yourself_has_no_added_by_line_on_the_edit_page(client, books):
    made = spend(client, books, "10", payee="Own")
    page = client.get(f"/transactions/{made['tid']}/edit").text
    assert "origin-foot" not in page and "Added by" not in page
