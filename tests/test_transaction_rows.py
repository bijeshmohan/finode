"""How a row of a list names itself (services/transaction_rows.py): the same for the web pages and the React app."""

from uuid import UUID

from app.services.transaction_rows import AccountIndex, to_row

from .books import category, leg, post_account
from .svc import services


def entry(client, *, payee=None, comment=None, postings):
    response = client.post("/api/transactions/", json={"payee": payee, "comment": comment, "postings": postings})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def row_of(session, transaction_id):
    svc = services(session)
    index = AccountIndex.build(svc.accounts.list(), svc.categories.list(include_closed=True))
    return to_row(svc.transactions.read(UUID(transaction_id)), index)


def test_a_row_names_itself_as_the_list_does(client, session, root_accounts):
    card = post_account(client, {"name": "Card", "parent_id": root_accounts["Liabilities"]}).json()
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "500"}).json()
    food = category(client, "Food")

    paid = entry(client, payee="Swiggy", postings=[leg(food, "debit", "30"), leg(card, "credit", "30")])
    plain = entry(client, postings=[leg(food, "debit", "10"), leg(card, "credit", "10")])
    noted = entry(client, payee="Cafe", comment="lunch", postings=[leg(food, "debit", "5"), leg(bank, "credit", "5")])

    swiggy = row_of(session, paid)
    assert (swiggy.title, swiggy.sub, swiggy.kind, swiggy.is_system) == ("Swiggy", "Card → Food", "expense", False)
    unnamed = row_of(session, plain)
    assert (unnamed.title, unnamed.sub) == ("Food", "Card")
    assert row_of(session, noted).sub == "Bank → Food · lunch"

    opening = next(
        t for t in client.get("/api/transactions/").json() if t["payee"] == "Opening balance" and t["comment"]
    )
    opened = row_of(session, opening["id"])
    assert opened.is_system and opened.sub == "Bank", "the system account and the stock note say nothing"
    assert opened.by_assistant is None and not opened.recurring


def test_an_assistants_entry_says_who_added_it(client, session, root_accounts):
    from app.models.transaction import Transaction

    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    food = category(client, "Food")
    made = entry(client, payee="Swiggy", postings=[leg(food, "debit", "30"), leg(bank, "credit", "30")])
    stored = session.get(Transaction, UUID(made))
    stored.created_via = "mcp:Claude"
    session.add(stored)
    session.commit()
    assert row_of(session, made).by_assistant == "Added by Claude"
