"""Tags in the web app: a #word in a note is shown apart on rows and in the sheet, found through the Filter sheet,
offered as it is typed, and listed with its uses. Nothing is stored for them; the note is the one place."""

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


def spend(client, books, amount, note=None, payee=None, to="travel", on=None):
    body = {
        "date": str(on or TODAY),
        "payee": payee,
        "comment": note,
        "postings": [
            {"account": books[to]["aid"], "side": "debit", "amount": amount},
            {"account": books["bank"]["aid"], "side": "credit", "amount": amount},
        ],
    }
    made = client.post("/api/transactions/", json=body)
    assert made.status_code == 201, made.text
    return made.json()


def earn(client, books, amount, note):
    made = client.post(
        "/api/transactions/",
        json={
            "date": str(TODAY),
            "comment": note,
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


# ---- rows and the sheet ---------------------------------------------------------------------------------------------


def test_a_row_shows_the_words_of_the_note_and_the_tags_apart(client, books):
    spend(client, books, "840", note="Dinner with Ravi #goa-trip #reimbursable", payee="Taj")
    page = client.get("/transactions").text
    sub = re.search(r'<span class="tx-sub">(.*?)</span>\s*</span>', page, re.S) or re.search(
        r'class="tx-sub">(.*)', page
    )
    html = sub.group(0)
    assert "Dinner with Ravi" in html and "Dinner with Ravi #goa-trip" not in html, "the words, then the tags"
    assert '<span class="tx-tag">#goa-trip</span> <span class="tx-tag">#reimbursable</span>' in page


def test_a_note_with_only_tags_leaves_just_the_tags_and_a_plain_note_is_unchanged(client, books):
    spend(client, books, "10", note="#goa-trip", payee="OnlyTag")
    spend(client, books, "20", note="Plain words, no tag", payee="Plain")
    spend(client, books, "30", note="Issue #1 is not a tag", payee="Number")
    page = client.get("/transactions").text
    assert '<span class="tx-tag">#goa-trip</span>' in page
    assert "Plain words, no tag" in page and page.count('class="tx-tag"') == 1, "#1 is not a tag"
    assert "Issue #1 is not a tag" in page, "a note keeps its words when what looks like a tag is not one"


def test_the_sheet_has_a_tags_row_that_filters_and_the_note_without_them(client, books):
    made = spend(client, books, "840", note="Airport drop #goa-trip #reimbursable", payee="Cab")
    sheet = client.get(f"/transactions/{made['tid']}/sheet").text
    assert f'href="/transactions?month={MONTH}&amp;tag=goa-trip">#goa-trip</a>' in sheet
    assert "#reimbursable</a>" in sheet
    note = re.search(r"<dt>Note</dt><dd>([^<]*)</dd>", sheet)
    assert note and note.group(1) == "Airport drop"
    only = spend(client, books, "5", note="#goa-trip", payee="Tag only")
    assert "<dt>Note</dt>" not in client.get(f"/transactions/{only['tid']}/sheet").text, "no empty note row"
    none = spend(client, books, "5", note="just words", payee="No tags")
    assert "<dt>Tags</dt>" not in client.get(f"/transactions/{none['tid']}/sheet").text


# ---- finding the entries --------------------------------------------------------------------------------------------


def test_the_tag_filter_lists_only_those_entries_and_says_what_they_come_to(client, books):
    spend(client, books, "840", note="Hotel #goa-trip", payee="Taj")
    spend(client, books, "160", note="#Goa-Trip cab", payee="Cab")
    spend(client, books, "999", note="Not this one #goa-tripping", payee="Other")
    spend(client, books, "50", note="no tag", payee="Plain")
    page = client.get("/transactions", params={"tag": "goa-trip"}).text
    assert sorted(titles(page)) == ["Cab", "Taj"], "capitals do not matter and a longer tag is another tag"
    body = text_of(page)
    assert "2 transactions" in body and "1,000.00 spent" in body
    assert '<a href="/transactions?month=' in page and "#goa-trip" in page and "Remove the tag filter" in page
    assert 'name="tag"' in page and 'data-filter-value="tag"' in page
    assert titles(client.get("/transactions", params={"tag": "#GOA-trip"}).text) == titles(page), (
        "a # and capitals are fine"
    )
    assert titles(client.get("/transactions", params={"tag": "nothing-here"}).text) == []


def test_the_tag_filter_combines_with_the_others_and_travels_with_show_more(client, books):
    for i in range(30):  # one a day, so no day has to be kept whole
        spend(
            client,
            books,
            "1",
            note="#bulk",
            payee=f"P{i:02d}",
            to="food" if i % 2 else "travel",
            on=date(2026, 1, 1 + i),
        )
    window = {"tag": "bulk", "date_from": "2026-01-01", "date_to": "2026-02-28"}
    first = client.get("/transactions", params=window).text
    assert len(titles(first)) == 25 and "Show 5 more" in first
    more = re.search(r'hx-get="(/transactions/more\?[^"]+)"', first).group(1).replace("&amp;", "&")
    assert "tag=bulk" in more
    assert len(titles(client.get(more).text)) == 5
    both = client.get("/transactions", params={**window, "category": books["food"]["aid"]}).text
    assert len(titles(both)) == 15


# ---- the lists the sheet and the form use -----------------------------------------------------------------------------


def test_the_tag_list_has_uses_last_day_and_the_total_when_they_all_go_one_way(client, books):
    spend(client, books, "840", note="#goa-trip", payee="A")
    spend(client, books, "160", note="#goa-trip #reimbursable", payee="B")
    earn(client, books, "500", note="Refund #reimbursable")
    html = client.get("/transactions/tag-options").text
    trip = re.search(r'data-value="goa-trip".*?</button>', html, re.S).group(0)
    assert "2 entries" in trip and "1,000.00" in trip and TODAY.strftime("%d %b") in trip
    mixed = re.search(r'data-value="reimbursable".*?</button>', html, re.S).group(0)
    assert "2 entries" in mixed and "00" not in re.sub(r"<small.*?</small>", "", mixed), (
        "spending and income mixed: no total"
    )


def test_the_tag_list_says_so_when_there_are_no_tags(client, books):
    spend(client, books, "5", note="words only", payee="X")
    assert "No tags yet" in client.get("/transactions/tag-options").text


def test_the_filter_sheet_has_a_tag_row_that_loads_its_list_when_opened(client, books):
    page = client.get("/transactions").text
    assert (
        'data-pick="tag"' in page
        and 'hx-get="/transactions/tag-options"' in page
        and 'hx-trigger="tags-open once"' in page
    )
    assert "goa-trip" not in page, "the tags are not read until the list is opened"


def test_the_names_for_the_add_screen_come_most_used_first(client, books):
    spend(client, books, "1", note="#b", payee="1")
    spend(client, books, "1", note="#a #b", payee="2")
    spend(client, books, "1", note="#a #b #c", payee="3")
    assert client.get("/transactions/tag-names").json() == [
        {"tag": "b", "uses": 3},
        {"tag": "a", "uses": 2},
        {"tag": "c", "uses": 1},
    ]


def test_the_note_on_the_add_screen_offers_tags(client, books):
    page = client.get("/transactions/new").text
    assert "data-tag-note" in page and 'class="tag-pop"' in page


def test_tags_are_case_insensitive_everywhere(client, books):
    spend(client, books, "100", note="Loan #emi", payee="A")
    spend(client, books, "200", note="Car loan #EMI", payee="B")
    spend(client, books, "300", note="Card #Emi", payee="C")
    # one tag in the lists, however it was typed, shown in lower case
    assert client.get("/transactions/tag-names").json() == [{"tag": "emi", "uses": 3}]
    options = client.get("/transactions/tag-options").text
    assert options.count('data-value="') == 1 and "3 entries" in options and "600.00" in options
    # every spelling finds all three
    for spelling in ("emi", "EMI", "#Emi", " #eMI "):
        found = titles(client.get("/transactions", params={"tag": spelling}).text)
        assert sorted(found) == ["A", "B", "C"], spelling
    # the rows and the sheet show it in one form, and the note keeps what was typed
    page = client.get("/transactions").text
    assert page.count('<span class="tx-tag">#emi</span>') == 3 and "#EMI" not in page and "#Emi" not in page
    made = client.get("/api/transactions/").json()
    typed = next(t for t in made if t["payee"] == "B")
    assert typed["comment"] == "Car loan #EMI", "the note is never rewritten"
