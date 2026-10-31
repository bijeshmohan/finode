"""A batch of entries is saved as one: all or none, safe to send again, and checked first with dry_run."""

import pytest

from app.config import settings

from .books import tool_leg
from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, make_token, mcp_client, payload, running_app
from .test_transaction_references import body


def entry(debit, credit, amount="10", **extra):
    return body(debit, credit, amount, **extra)


def count(client):
    return len(client.get("/api/transactions/").json())


def test_every_entry_of_a_batch_is_saved(client, account, expense_account):
    sent = [entry(expense_account, account, str(n), source="bank", external_id=f"r{n}") for n in (1, 2, 3)]
    answer = client.post("/api/transactions/batch", json={"transactions": sent})
    assert answer.status_code == 201, answer.text
    result = answer.json()
    assert (result["saved"], result["created"], result["already_recorded"]) == (True, 3, 0)
    assert [e["item"] for e in result["entries"]] == [1, 2, 3] and {e["status"] for e in result["entries"]} == {
        "recorded"
    }
    assert count(client) == 3


def test_one_bad_entry_saves_nothing_and_every_problem_is_named(client, account, expense_account):
    sent = [
        entry(expense_account, account, "10"),
        entry(expense_account, account, "1.005"),
        entry(expense_account, account, "30"),
        entry(account, account, "5"),  # the same account on both sides
    ]
    answer = client.post("/api/transactions/batch", json={"transactions": sent})
    assert answer.status_code == 400
    detail = answer.json()["detail"]
    assert detail.startswith("nothing was saved.") and "entry 2:" in detail and "entry 4:" in detail
    assert "entry 1:" not in detail and "entry 3:" not in detail
    assert count(client) == 0


def test_a_batch_can_be_sent_again(client, account, expense_account):
    sent = [entry(expense_account, account, str(n), source="bank", external_id=f"r{n}") for n in (1, 2)]
    client.post("/api/transactions/batch", json={"transactions": sent})
    more = [*sent, entry(expense_account, account, "3", source="bank", external_id="r3")]
    again = client.post("/api/transactions/batch", json={"transactions": more})
    assert again.status_code == 201
    result = again.json()
    assert [e["status"] for e in result["entries"]] == ["already_recorded", "already_recorded", "recorded"]
    assert (result["created"], result["already_recorded"]) == (1, 2) and count(client) == 3
    nothing_new = client.post("/api/transactions/batch", json={"transactions": sent})
    assert nothing_new.status_code == 200 and nothing_new.json()["created"] == 0


def test_a_reference_repeated_inside_a_batch_or_with_other_content_is_refused(client, account, expense_account):
    twice = [entry(expense_account, account, "1", source="bank", external_id="x")] * 2
    answer = client.post("/api/transactions/batch", json={"transactions": twice})
    assert answer.status_code == 400 and "entry 2: it repeats" in answer.json()["detail"]
    client.post("/api/transactions/", json=entry(expense_account, account, "1", source="bank", external_id="x"))
    changed = [entry(expense_account, account, "2", source="bank", external_id="x")]
    assert client.post("/api/transactions/batch", json={"transactions": changed}).status_code == 400
    assert count(client) == 1


def test_a_dry_run_shows_the_batch_and_saves_nothing(client, account, expense_account):
    client.post("/api/transactions/", json=entry(expense_account, account, "1", source="bank", external_id="x"))
    sent = [entry(expense_account, account, "1", source="bank", external_id="x"), entry(expense_account, account, "5")]
    answer = client.post("/api/transactions/batch?dry_run=true", json={"transactions": sent})
    assert answer.status_code == 200
    result = answer.json()
    assert (result["dry_run"], result["saved"], result["created"]) == (True, False, 0)
    assert [e["status"] for e in result["entries"]] == ["already_recorded", "would_record"]
    assert count(client) == 1


def test_the_size_and_the_limits_of_a_batch(client, account, expense_account, monkeypatch):
    assert client.post("/api/transactions/batch", json={"transactions": []}).status_code == 422
    too_many = [entry(expense_account, account)] * 51
    assert client.post("/api/transactions/batch", json={"transactions": too_many}).status_code == 422
    monkeypatch.setattr(settings, "max_transactions_per_day", 3)
    four = [entry(expense_account, account, str(n)) for n in (1, 2, 3, 4)]
    answer = client.post("/api/transactions/batch", json={"transactions": four})
    assert answer.status_code == 400 and "limit" in answer.json()["detail"] and count(client) == 0
    assert client.post("/api/transactions/batch", json={"transactions": four[:3]}).status_code == 201


def test_a_failure_while_saving_leaves_nothing_behind(client, account, expense_account, monkeypatch):
    from app.repositories.transaction import TransactionRepository

    real = TransactionRepository.create
    calls = []

    def flaky(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("the database went away")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(TransactionRepository, "create", flaky)
    sent = [entry(expense_account, account, str(n)) for n in (1, 2, 3, 4)]
    with pytest.raises(RuntimeError):
        client.post("/api/transactions/batch", json={"transactions": sent})
    monkeypatch.setattr(TransactionRepository, "create", real)
    assert count(client) == 0
    assert client.get("/api/reports/trial-balance").json()["balanced"] is True


@pytest.mark.anyio
async def test_assistants_record_a_batch_in_one_call(session, client, account, expense_account):
    rows = [
        tool_leg(account, "credit", "30"),
        tool_leg(expense_account, "debit", "30"),
    ]
    entries = [
        {
            "amount": "10",
            "from_account": account["id"],
            "to_account": expense_account["id"],
            "payee": "A",
            "external_id": "e1",
            "source": "emi",
        },
        {"postings": rows, "payee": "B", "external_id": "e2", "source": "emi"},
    ]
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
        checked = payload(await c.call_tool("record_transactions", {"entries": entries, "dry_run": True}))
        assert checked["saved"] is False and checked["entries"][1]["status"] == "would_record" and count(client) == 0
        done = payload(await c.call_tool("record_transactions", {"entries": entries}))
        assert done["recorded"] == 2 and done["entries"][0]["transaction"]["reference"]["external_id"] == "e1"
        again = payload(await c.call_tool("record_transactions", {"entries": entries}))
        assert again["recorded"] == 0 and again["already_recorded"] == 2 and count(client) == 2
        bad = [
            entries[0],
            {"amount": "5", "from_account": "Nowhere", "to_account": expense_account["id"]},
            {"payee": "x"},
        ]
        with pytest.raises(ToolFailed, match=r"nothing was saved\. entry 2: .*entry 3: "):
            payload(await c.call_tool("record_transactions", {"entries": bad}))
        assert count(client) == 2


@pytest.mark.anyio
async def test_a_read_only_connection_may_only_check_a_batch(session, client, account, expense_account):
    entries = [{"amount": "10", "from_account": account["id"], "to_account": expense_account["id"]}]
    async with running_app(session), mcp_client(make_token(session, TEST_USER_ID, scope="read")) as c:
        assert (
            payload(await c.call_tool("record_transactions", {"entries": entries, "dry_run": True}))["saved"] is False
        )
        with pytest.raises(ToolFailed, match="read-only"):
            payload(await c.call_tool("record_transactions", {"entries": entries}))
        assert count(client) == 0
