"""Categories for tests: what used to be an Expenses or Income account is a category now, and a line names it as its
`category_id` (it posts to Expenses or Income)."""


def category(client, name, kind="spending", parent=None, **extra):
    """Make a category through the API."""
    body = {"name": name, "kind": kind, **extra}
    if parent is not None:
        body["parent_id"] = parent["id"] if isinstance(parent, dict) else parent
    response = client.post("/api/categories/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


class Made:
    """The answer to creating an account or a category, whichever it turned out to be."""

    def __init__(self, response):
        self.response, self.status_code, self.text = response, response.status_code, response.text

    def json(self):
        return self.response.json()


def post_account(client, body):
    """Create an account, or a category when the account would sit under Expenses or Income (or inside a category):
    those hold categories now. `body` is what POST /api/accounts/ takes."""
    roots = {a["id"]: a["name"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}
    parent = body.get("parent_id")
    kinds = {c["id"]: c["kind"] for c in client.get("/api/categories/", params={"include_closed": True}).json()}
    if roots.get(parent) in ("Expenses", "Income") or parent in kinds:
        kind = ("spending" if roots[parent] == "Expenses" else "earning") if parent in roots else kinds[parent]
        send = {"name": body["name"], "kind": kind, "details": body.get("details")}
        if parent in kinds:
            send["parent_id"] = parent
        return Made(client.post("/api/categories/", json=send))
    return client.post("/api/accounts/", json=body)


def leg(place, side, amount, **extra):
    """One line of an entry for the API: a category is named as `category_id` (it posts to Expenses or Income), an
    account as `account_id`. `place` is what the fixtures return (a category has a `kind`)."""
    key = "category_id" if "kind" in place else "account_id"
    return {key: place["id"], "side": side, "amount": amount, **extra}


def into(client, category):
    """The fields of a simple recurring rule that pays a category: it records on Expenses or Income, with the category."""
    roots = {a["name"]: a["id"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}
    kind = category.get("kind") or next(
        c["kind"] for c in client.get("/api/categories/").json() if c["id"] == category["id"]
    )
    return {"to_account_id": roots["Expenses" if kind == "spending" else "Income"], "category_id": category["id"]}


def tool_leg(place, side, amount, **extra):
    """One row for an assistant's tool: it names a place (an id works as well as a path), as `account` or `category`."""
    key = "category" if "kind" in place else "account"
    return {key: place["id"], "side": side, "amount": amount, **extra}
