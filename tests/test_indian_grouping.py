"""Rupees are grouped in lakhs and crores (12,34,567.00); every other currency in thousands (1,234,567.00)."""

import pytest

from app.templating import group_digits, grouping_for, money


@pytest.mark.parametrize("value, indian, western", [
    ("0", "0.00", "0.00"),
    ("999", "999.00", "999.00"),
    ("1000", "1,000.00", "1,000.00"),
    ("99999.5", "99,999.50", "99,999.50"),
    ("100000", "1,00,000.00", "100,000.00"),
    ("1234567", "12,34,567.00", "1,234,567.00"),
    ("123456789", "12,34,56,789.00", "123,456,789.00"),
    ("-1234567.891", "−12,34,567.891", "−1,234,567.891"),
])
def test_the_two_ways_of_grouping(value, indian, western):
    assert money(value, "indian") == indian and money(value, "western") == western


def test_only_the_rupee_is_grouped_in_lakhs():
    assert grouping_for("INR") == "indian"
    assert all(grouping_for(code) == "western" for code in ("USD", "EUR", "JPY", "PKR", None))
    assert group_digits("12345678", "indian") == "1,23,45,678"


@pytest.fixture
def lakhs(client, root_accounts):
    bank = client.post("/api/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1234567"}).json()
    food = client.post("/api/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    return bank, food


def test_pages_group_rupees_in_lakhs_and_crores(client, lakhs):
    assert "12,34,567.00" in client.get("/accounts").text
    assert "1,234,567" not in client.get("/accounts").text
    assert 'data-grouping="indian"' in client.get("/").text, "the page tells the scripts which way to group"
    assert "12,34,567.00" in client.get("/budget").text


def test_another_currency_keeps_thousands(client, lakhs):
    assert client.patch("/api/profile/", json={"default_currency": "USD"}).status_code == 200
    page = client.get("/accounts").text
    assert "1,234,567.00" in page and "12,34,567" not in page
    assert 'data-grouping="western"' in client.get("/").text


def test_budget_hints_follow_the_grouping(client, lakhs):
    bank, food = lakhs
    from datetime import date
    month = date.today().replace(day=1).isoformat()
    client.put(f"/api/budget/categories/{food['aid']}", json={"month": month, "amount": "100"})
    client.put(f"/api/budget/categories/{food['aid']}/target", json={"kind": "monthly", "amount": "250000"})
    page = client.get("/budget").text
    assert "needs 2,49,900.00 more" in page


def test_the_page_tells_the_scripts_how_many_decimals_the_currency_keeps(client):
    assert 'data-places="2"' in client.get("/").text
    assert client.patch("/api/profile/", json={"default_currency": "JPY"}).status_code == 200
    assert 'data-places="0"' in client.get("/").text
