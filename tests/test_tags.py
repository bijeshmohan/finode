"""Tags are their own thing on an entry (a tags table), apart from the note. `tags_in` and `split_note` stay only to
move the #words of older notes and backups into tags."""

import pytest

from app.tags import clean_name, clean_names, clean_tag, split_note, tags_in

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app
from .test_transaction_references import body


@pytest.mark.parametrize(
    ("note", "tags"),
    [
        ("Dinner with Ravi #Reimbursable #goa-trip", ["reimbursable", "goa-trip"]),
        ("#first at the start", ["first"]),
        ("twice #goa #GOA", ["goa"]),
        ("punctuation #goa, #trip. #x!", ["goa", "trip", "x"]),
        ("#1 and #123 are numbers, not tags", []),
        ("no#glue and a#b and C# here", []),
        ("trailing dash #goa- or #a_", ["goa", "a"]),
        ("#" + "a" * 30 + " ok but #" + "b" * 31 + " too long", ["a" * 30]),
        ("", []),
        (None, []),
        ("##double and #-dash", []),
    ],
)
def test_tags_in_a_note(note, tags):
    assert tags_in(note) == tags


def test_clean_tag():
    assert clean_tag(" #Goa-Trip ") == "goa-trip" and clean_tag("goa") == "goa"


def test_clean_names():
    assert clean_names(["#Goa-Trip", " goa-trip ", "EMI"]) == ["goa-trip", "emi"]
    assert clean_name("#Emi") == "emi"
    for bad in ("", "#", "1", "a b", "a" * 31, "-x", "x-", "naïve"):
        with pytest.raises(ValueError):
            clean_name(bad)
    with pytest.raises(ValueError, match="at most 10"):
        clean_names([f"t{n}" for n in range(11)])


def test_old_notes_split_into_words_and_tags():
    assert split_note("Dinner with Ravi #goa-trip #reimbursable") == ("Dinner with Ravi", ["goa-trip", "reimbursable"])
    assert split_note("#only") == (None, ["only"])
    assert split_note("Ride paid through #UPI") == ("Ride paid through UPI", ["upi"]), (
        "part of the sentence: the word stays"
    )
    assert split_note("Lunch with #Ravi #work") == ("Lunch with Ravi", ["ravi", "work"])
    assert split_note("no tags here") == ("no tags here", [])
    assert split_note("Issue #1") == ("Issue #1", [])
    many = " ".join(f"#t{n}" for n in range(11))
    assert split_note(many) == (many, []), "too many tags: the note is left as it is"


def make(client, account, expense, note=None, tags=None, on="2026-10-10", amount="10"):
    extra = {"comment": note}
    if tags is not None:
        extra["tags"] = tags
    made = client.post("/api/transactions/", json=body(expense, account, amount, on=on, **extra))
    assert made.status_code == 201, made.text
    return made.json()


def test_an_entry_reads_back_its_tags_and_can_be_found_by_them(client, account, expense_account):
    one = make(client, account, expense_account, "Taxi", ["Reimbursable", "work"], on="2026-10-01")
    make(client, account, expense_account, "Lunch", ["reimbursable"], on="2026-10-02")
    make(client, account, expense_account, "Plain note", on="2026-10-03")
    make(client, account, expense_account, "Trip", ["goa-trip"], on="2026-10-04")
    assert one["tags"] == ["reimbursable", "work"] and one["comment"] == "Taxi", "the note is left alone"
    found = client.get("/api/transactions/", params={"tag": "#Reimbursable"}).json()
    assert [t["comment"] for t in found] == ["Lunch", "Taxi"]
    assert client.get("/api/transactions/", params={"tag": "goa"}).json() == []
    assert len(client.get("/api/transactions/", params={"tag": "goa-trip"}).json()) == 1
    assert client.get(f"/api/transactions/{one['tid']}").json()["tags"] == ["reimbursable", "work"]


def test_a_hash_in_a_note_is_only_text(client, account, expense_account):
    made = make(client, account, expense_account, "Taxi #reimbursable")
    assert made["tags"] == [] and made["comment"] == "Taxi #reimbursable"
    assert client.get("/api/tags/").json() == []


def test_a_tag_search_pages_after_the_match(client, account, expense_account):
    for n in range(5):
        make(client, account, expense_account, f"n{n}", ["t"], on=f"2026-10-0{n + 1}")
        make(client, account, expense_account, f"other {n}", on=f"2026-10-0{n + 1}")
    page = client.get("/api/transactions/", params={"tag": "t", "limit": 2, "offset": 2}).json()
    assert [t["comment"] for t in page] == ["n2", "n1"]


def test_the_tags_in_use(client, account, expense_account):
    make(client, account, expense_account, "a", ["work", "lunch"], on="2026-10-01")
    make(client, account, expense_account, "b", ["work"], on="2026-10-05")
    make(client, account, expense_account, "c", ["Work"], on="2026-10-03")
    assert client.get("/api/tags/").json() == [
        {"tag": "work", "uses": 3, "last_used": "2026-10-05"},
        {"tag": "lunch", "uses": 1, "last_used": "2026-10-01"},
    ]


def test_updating_tags_replaces_keeps_or_clears_them(client, account, expense_account):
    made = make(client, account, expense_account, "Taxi", ["a", "b"])
    url = f"/api/transactions/{made['tid']}"
    assert client.patch(url, json={"payee": "Cab"}).json()["tags"] == ["a", "b"], "left out: kept"
    assert client.patch(url, json={"tags": ["b", "C"]}).json()["tags"] == ["b", "c"], "given: replaced"
    assert [t["tag"] for t in client.get("/api/tags/").json()] == ["b", "c"], "a tag nobody has any more is gone"
    assert client.patch(url, json={"tags": []}).json()["tags"] == []
    assert client.get("/api/tags/").json() == []


def test_bad_tags_are_refused(client, account, expense_account):
    made = make(client, account, expense_account, "Taxi")
    assert client.patch(f"/api/transactions/{made['tid']}", json={"tags": ["not valid"]}).status_code == 422
    too_many = body(expense_account, account, "5", tags=[f"t{n}" for n in range(11)])
    assert client.post("/api/transactions/", json=too_many).status_code == 422


def test_a_person_has_only_so_many_tags(client, account, expense_account, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_tags", 2)
    make(client, account, expense_account, "a", ["one", "two"])
    refused = client.post("/api/transactions/", json=body(expense_account, account, "5", tags=["three"]))
    assert refused.status_code == 400 and "limit" in refused.text
    assert client.post("/api/transactions/", json=body(expense_account, account, "5", tags=["one"])).status_code == 201


def test_deleting_an_entry_and_restoring_it_brings_its_tags_back(client, account, expense_account, svc):
    made = make(client, account, expense_account, "Taxi", ["a", "b"])
    client.delete(f"/api/transactions/{made['tid']}")
    assert client.get("/api/tags/").json() == [], "no entry carries them now"
    gone = client.get("/api/transactions/deleted").json()
    restored = client.post(f"/api/transactions/deleted/{gone[0]['hid']}/restore")
    assert restored.status_code == 200 and restored.json()["tags"] == ["a", "b"]
    assert [t["tag"] for t in client.get("/api/tags/").json()] == ["a", "b"]


def test_the_history_notes_a_changed_tag_but_not_an_unchanged_one(client, account, expense_account):
    made = make(client, account, expense_account, "Taxi", ["a"])
    url = f"/api/transactions/{made['tid']}"
    client.patch(url, json={"tags": ["a"]})
    assert len(client.get(f"{url}/history").json()) == 1
    client.patch(url, json={"tags": ["a", "b"]})
    history = client.get(f"{url}/history").json()
    assert [h["action"] for h in history] == ["created", "updated"]


def test_renaming_merging_and_deleting_tags(client, account, expense_account):
    first = make(client, account, expense_account, "1", ["trip", "x"])
    second = make(client, account, expense_account, "2", ["goa-trip"])
    third = make(client, account, expense_account, "3", ["trip", "goa-trip"])
    renamed = client.patch("/api/tags/x", json={"name": "#Y"})
    assert renamed.status_code == 200 and renamed.json()["tag"] == "y"
    merged = client.patch("/api/tags/trip", json={"name": "goa-trip"})
    assert merged.status_code == 200 and merged.json()["tag"] == "goa-trip" and merged.json()["uses"] == 3
    reads = {t["tid"]: t["tags"] for t in client.get("/api/transactions/").json()}
    assert reads[first["tid"]] == ["goa-trip", "y"] and reads[second["tid"]] == ["goa-trip"]
    assert reads[third["tid"]] == ["goa-trip"], "an entry that had both has the one"
    assert [t["tag"] for t in client.get("/api/tags/").json()] == ["goa-trip", "y"]
    assert client.patch("/api/tags/nothing", json={"name": "z"}).status_code == 404
    assert client.patch("/api/tags/y", json={"name": "y"}).status_code == 400
    assert client.patch("/api/tags/y", json={"name": "not valid"}).status_code == 400
    assert client.delete("/api/tags/y").status_code == 204
    assert client.get(f"/api/transactions/{first['tid']}").json()["tags"] == ["goa-trip"]
    assert client.delete("/api/tags/y").status_code == 404


def test_deleting_the_entry_that_has_a_tag_drops_the_tag(client, account, expense_account):
    made = make(client, account, expense_account, "1", ["only-here"])
    client.delete(f"/api/transactions/{made['tid']}")
    assert client.get("/api/tags/").json() == []


@pytest.mark.anyio
async def test_assistants_put_tags_on_entries(session, client, account, expense_account):
    made = make(client, account, expense_account, "Taxi")
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        updated = payload(
            await c.call_tool("update_transaction", {"transaction_id": made["tid"], "tags": ["Reimbursable"]})
        )
        assert updated["updated"]["tags"] == ["reimbursable"] and updated["updated"]["note"] == "Taxi"
        more = payload(
            await c.call_tool(
                "update_transaction", {"transaction_id": made["tid"], "add_tags": ["work", "reimbursable"]}
            )
        )
        assert more["updated"]["tags"] == ["reimbursable", "work"]
        less = payload(
            await c.call_tool("update_transaction", {"transaction_id": made["tid"], "remove_tags": ["reimbursable"]})
        )
        assert less["updated"]["tags"] == ["work"]
        listed = payload(await c.call_tool("list_tags", {}))["tags"]
        assert [t["tag"] for t in listed] == ["work"]
        found = payload(await c.call_tool("search_transactions", {"tag": "work"}))
        assert found["count"] == 1 and found["transactions"][0]["tags"] == ["work"]
        assert payload(await c.call_tool("search_transactions", {"tag": "nope"}))["count"] == 0
        recorded = payload(
            await c.call_tool(
                "record_transaction",
                {
                    "amount": "5",
                    "from_account": account["name"],
                    "to_account": expense_account["name"],
                    "tags": ["lunch"],
                },
            )
        )
        assert recorded["recorded"]["tags"] == ["lunch"] and "notice" not in recorded


@pytest.mark.anyio
async def test_a_hash_in_a_note_written_by_an_assistant_gets_a_notice(session, client, account, expense_account):
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        recorded = payload(
            await c.call_tool(
                "record_transaction",
                {
                    "amount": "5",
                    "from_account": account["name"],
                    "to_account": expense_account["name"],
                    "note": "Lunch #work",
                },
            )
        )
        assert "tags" not in recorded["recorded"] and "not read from the note" in recorded["notice"]


@pytest.mark.anyio
async def test_renaming_merging_and_deleting_tags_need_the_manage_level(session, client, account, expense_account):
    make(client, account, expense_account, "1", ["a"])
    make(client, account, expense_account, "2", ["b"])
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="write")) as c:
        for tool, args in (
            ("rename_tag", {"tag": "a", "new_name": "z"}),
            ("merge_tags", {"source": "a", "target": "b"}),
            ("delete_tag", {"tag": "a"}),
        ):
            with pytest.raises(ToolFailed, match="not manage accounts, categories or tags"):
                payload(await c.call_tool(tool, args))
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, name="M", scope="manage")) as c:
        renamed = payload(await c.call_tool("rename_tag", {"tag": "a", "new_name": "Z"}))
        assert renamed["to"] == "z" and renamed["entries_with_it_now"] == 1
        merged = payload(await c.call_tool("merge_tags", {"source": "z", "target": "b"}))
        assert merged["into"] == "b" and merged["entries_with_it_now"] == 2
        with pytest.raises(ToolFailed, match="no tag"):
            payload(await c.call_tool("merge_tags", {"source": "b", "target": "nope"}))
        gone = payload(await c.call_tool("delete_tag", {"tag": "b"}))
        assert gone["entries_it_was_on"] == 2
