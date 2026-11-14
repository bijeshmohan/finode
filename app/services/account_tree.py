"""The accounts as a tree under the five roots, in the order the app shows them: shared by every list of accounts."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..schemas import AccountRead
from .account import AccountService

ROOT_ORDER = ("Assets", "Liabilities", "Equity", "Income", "Expenses")


@dataclass
class Node:
    account: AccountRead
    depth: int = 0
    kind: str = "user"  # root | system | user
    path: str = ""
    postable: bool = False
    children: list[Node] = field(default_factory=list)
    # For the accounts page: whether the account is closed (closed ones wait behind "Load more").
    closed: bool = False

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def is_group(self) -> bool:
        """A shelf for accounts: a built-in group or one the person made (even empty), or an account with accounts in it."""
        return self.account.new_accounts_in_budget is not None or bool(self.children)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def build_tree(accounts: list[AccountRead]) -> list[Node]:
    """The accounts as a tree."""
    nodes = {a.id: Node(a) for a in accounts}
    roots: list[Node] = []
    for node in nodes.values():
        parent = nodes.get(node.account.parent_id) if node.account.parent_id else None
        if parent is None:
            node.kind = "root"
            roots.append(node)
        else:
            parent.children.append(node)
            if AccountService.is_opening_balances(node.account, accounts):
                node.kind = "system"
            elif node.account.system_key:
                node.kind = "fixed"  # a built-in group (Bank Accounts, Cash, Investments, Credit Cards, Loans)

    def finish(node: Node, depth: int, parent_path: str = "") -> None:
        node.depth = depth
        node.postable = (
            node.kind not in ("root", "fixed") and node.account.new_accounts_in_budget is None and node.is_leaf
        )
        node.path = f"{parent_path} › {node.account.name}" if parent_path else node.account.name
        node.children.sort(key=lambda n: AccountService.order_key(n.account))
        for child in node.children:
            finish(child, depth + 1, node.path)

    roots.sort(key=lambda n: ROOT_ORDER.index(n.account.name) if n.account.name in ROOT_ORDER else len(ROOT_ORDER))
    for root in roots:
        finish(root, 0)
    return roots


def without_contacts(roots: list[Node]) -> list[Node]:
    """The tree without a contact's "Due from" and "Due to" accounts: they belong to the People pages, not to the Accounts
    page or the pickers."""
    for node in roots:
        node.children = [c for c in node.children if not c.account.contact_account]
        without_contacts(node.children)
    return roots
