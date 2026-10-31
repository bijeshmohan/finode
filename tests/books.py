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


class Made:
    """The answer to creating an account or a category, shaped like an account's (it has `aid`)."""

    def __init__(self, response):
        self.response, self.status_code, self.text = response, response.status_code, response.text

    def json(self):
        body = self.response.json()
        if isinstance(body, dict) and "bcid" in body:
            body["aid"] = body["bcid"]
        return body


def post_account(client, body):
    """Create an account, or a category when the account would sit under Expenses or Income (or inside a category):
    those hold categories now. `body` is what POST /api/accounts/ takes."""
    roots = {a["aid"]: a["name"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}
    parent = body.get("parent_id")
    kinds = {c["bcid"]: c["kind"] for c in client.get("/api/categories/", params={"include_closed": True}).json()}
    if roots.get(parent) in ("Expenses", "Income") or parent in kinds:
        kind = ("spending" if roots[parent] == "Expenses" else "earning") if parent in roots else kinds[parent]
        send = {"name": body["name"], "kind": kind, "details": body.get("details")}
        if parent in kinds:
            send["parent_id"] = parent
        return Made(client.post("/api/categories/", json=send))
    return client.post("/api/accounts/", json=body)


def leg(place, side, amount, **extra):
    """One line of an entry for the API: a category is named as `category` (it posts to Expenses or Income), an account
    as `account`. `place` is what the fixtures return (a category has `bcid`)."""
    key = "category" if "bcid" in place else "account"
    return {key: place["bcid"] if key == "category" else place["aid"], "side": side, "amount": amount, **extra}
