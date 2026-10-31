"""An entry can say where it came from (source, external_id, source_url); a source's reference is used once."""

import pytest

from .books import leg
from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app

PAY = {"source": "gmail", "external_id": "msg-1", "source_url": "https://mail.example.com/msg-1"}


def body(debit, credit, amount="100", on="2026-10-10", **extra):
    return {
        "date": on,
        "payee": "Shop",
        "postings": [
            leg(debit, "debit", amount),
            leg(credit, "credit", amount),
        ],
        **extra,
    }


def test_the_reference_is_stored_and_read_back(client, account, expense_account):
    made = client.post("/api/transactions/", json=body(expense_account, account, **PAY))
    assert made.status_code == 201, made.text
    assert (made.json()["source"], made.json()["external_id"]) == ("gmail", "msg-1")
    again = client.get(f"/api/transactions/{made.json()['tid']}").json()
    assert again["source_url"] == PAY["source_url"]


def test_recording_the_same_reference_again_finds_the_entry(client, account, expense_account):
    first = client.post("/api/transactions/", json=body(expense_account, account, **PAY))
    second = client.post("/api/transactions/", json=body(expense_account, account, payee="Shop", **PAY))
    assert second.status_code == 200 and second.json()["tid"] == first.json()["tid"]
    assert len(client.get("/api/transactions/").json()) == 1, "no copy was made"


def test_the_same_reference_with_other_content_is_refused(client, account, expense_account):
    client.post("/api/transactions/", json=body(expense_account, account, **PAY))
    other_amount = client.post("/api/transactions/", json=body(expense_account, account, amount="101", **PAY))
    assert other_amount.status_code == 400 and "different" in other_amount.json()["detail"]
    other_day = client.post("/api/transactions/", json=body(expense_account, account, on="2026-10-11", **PAY))
    assert other_day.status_code == 400


def test_a_reference_needs_a_source_and_a_link_must_be_a_web_address(client, account, expense_account):
    assert client.post("/api/transactions/", json=body(expense_account, account, external_id="x")).status_code == 422
    bad = body(expense_account, account, source="gmail", source_url="javascript:alert(1)")
    assert client.post("/api/transactions/", json=bad).status_code == 422


def test_source_is_tidied_and_references_are_per_source(client, account, expense_account):
    one = client.post("/api/transactions/", json=body(expense_account, account, source=" GMail ", external_id="7"))
    assert one.json()["source"] == "gmail"
    other = client.post("/api/transactions/", json=body(expense_account, account, source="upi", external_id="7"))
    assert other.status_code == 201 and other.json()["tid"] != one.json()["tid"]


def test_entries_are_found_by_their_reference(client, account, expense_account):
    made = client.post("/api/transactions/", json=body(expense_account, account, **PAY)).json()
    client.post("/api/transactions/", json=body(expense_account, account, on="2026-10-12"))
    found = client.get("/api/transactions/", params={"source": "gmail", "external_id": "msg-1"}).json()
    assert [t["tid"] for t in found] == [made["tid"]]
    assert len(client.get("/api/transactions/", params={"source": "GMAIL"}).json()) == 1


def test_a_reference_can_be_added_changed_cleared_but_not_taken(client, account, expense_account):
    plain = client.post("/api/transactions/", json=body(expense_account, account)).json()
    taken = client.post("/api/transactions/", json=body(expense_account, account, on="2026-10-11", **PAY)).json()
    clash = client.patch(f"/api/transactions/{plain['tid']}", json={"source": "gmail", "external_id": "msg-1"})
    assert clash.status_code == 400 and taken["tid"] in clash.json()["detail"]
    ok = client.patch(f"/api/transactions/{plain['tid']}", json={"source": "upi", "external_id": "u-1"})
    assert ok.status_code == 200 and ok.json()["external_id"] == "u-1"
    assert client.patch(f"/api/transactions/{plain['tid']}", json={"note": None}).json()["external_id"] == "u-1"
    cleared = client.patch(f"/api/transactions/{plain['tid']}", json={"external_id": None, "source": None})
    assert cleared.json()["external_id"] is None and cleared.json()["source"] is None
    no_source = client.patch(f"/api/transactions/{plain['tid']}", json={"external_id": "z"})
    assert no_source.status_code == 400, "an entry with no source cannot gain a bare reference"


def test_deleting_frees_the_reference_and_restoring_gives_it_back(client, account, expense_account):
    first = client.post("/api/transactions/", json=body(expense_account, account, **PAY)).json()
    assert client.delete(f"/api/transactions/{first['tid']}").status_code == 204
    hid = client.get("/api/transactions/deleted").json()[0]["hid"]
    second = client.post("/api/transactions/", json=body(expense_account, account, **PAY))
    assert second.status_code == 201, "the reference was free again"
    refused = client.post(f"/api/transactions/deleted/{hid}/restore")
    assert refused.status_code == 400 and "already used" in refused.json()["detail"]
    client.delete(f"/api/transactions/{second.json()['tid']}")
    newest = client.get("/api/transactions/deleted").json()[0]["hid"]
    back = client.post(f"/api/transactions/deleted/{newest}/restore")
    assert back.status_code == 200 and back.json()["external_id"] == "msg-1"


def test_the_details_sheet_names_the_source(client, account, expense_account):
    made = client.post("/api/transactions/", json=body(expense_account, account, **PAY)).json()
    sheet = client.get(f"/transactions/{made['tid']}/sheet").text
    assert "gmail" in sheet and "msg-1" in sheet and 'href="https://mail.example.com/msg-1"' in sheet
    plain = client.post("/api/transactions/", json=body(expense_account, account, on="2026-10-12")).json()
    assert "Source" not in client.get(f"/transactions/{plain['tid']}/sheet").text


@pytest.mark.anyio
async def test_assistants_can_record_safely_twice(session, client, account, expense_account):
    secret = make_token(session, TEST_USER_ID)
    async with running_app(session), mcp_client(secret) as c:
        args = {
            "amount": "250",
            "from_account": account["aid"],
            "to_account": expense_account["aid"],
            "payee": "DMart",
            "source": "bank-sms",
            "external_id": "UPI/4471",
        }
        first = payload(await c.call_tool("record_transaction", args))
        assert "already_recorded" not in first and first["recorded"]["reference"]["external_id"] == "UPI/4471"
        again = payload(await c.call_tool("record_transaction", args))
        assert again["already_recorded"] is True and again["recorded"]["id"] == first["recorded"]["id"]
        found = payload(await c.call_tool("search_transactions", {"source": "bank-sms", "external_id": "UPI/4471"}))
        assert found["count"] == 1
        with pytest.raises(ToolFailed, match="different"):
            payload(await c.call_tool("record_transaction", args | {"amount": "251"}))
        changed = payload(
            await c.call_tool(
                "update_transaction",
                {"transaction_id": first["recorded"]["id"], "source_url": "https://bank.example/tx/4471"},
            )
        )
        assert changed["updated"]["reference"]["url"] == "https://bank.example/tx/4471"
