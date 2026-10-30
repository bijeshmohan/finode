"""Categories for tests: what used to be an Expenses or Income account is a category now (its id works wherever an
account id is taken on an entry's line, so the tests keep reading as before)."""


def category(client, name, kind="spending", parent=None, **extra):
    """Make a category through the API; the answer carries `aid` (the same as `bcid`) as accounts do."""
    body = {"name": name, "kind": kind, **extra}
    if parent is not None:
        body["parent_id"] = parent["bcid"] if isinstance(parent, dict) else parent
    response = client.post("/api/categories/", json=body)
    assert response.status_code == 201, response.text
    made = response.json()
    made["aid"] = made["bcid"]
    return made
