"""Persistence for shared expenses and their shares and contributions, always filtered by the user's id."""

import builtins
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, col, select, update

from ..models.contact import ExpenseContribution, ExpenseShare, SharedExpense


class SharedExpenseRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def read(self, expense_id: UUID, lock: bool = False) -> SharedExpense | None:
        """One expense; `lock` takes a row lock on Postgres so two confirmations of it queue up."""
        statement = select(SharedExpense).where(SharedExpense.user_id == self.uid, SharedExpense.id == expense_id)
        if lock:
            statement = statement.with_for_update()
        return self.db.exec(statement).first()

    def list(self, status: str | None = None) -> builtins.list[SharedExpense]:
        statement = select(SharedExpense).where(SharedExpense.user_id == self.uid)
        if status is not None:
            statement = statement.where(SharedExpense.status == status)
        return list(self.db.exec(statement.order_by(col(SharedExpense.date).desc(), col(SharedExpense.created).desc())))

    def by_transaction(self, transaction_id: UUID) -> SharedExpense | None:
        return self.db.exec(
            select(SharedExpense).where(
                SharedExpense.user_id == self.uid, SharedExpense.transaction_id == transaction_id
            )
        ).first()

    def by_transactions(self, transaction_ids: builtins.list[UUID]) -> dict[UUID, SharedExpense]:
        """The expenses behind several ledger entries in one query, by the entry."""
        if not transaction_ids:
            return {}
        rows = self.db.exec(
            select(SharedExpense).where(
                SharedExpense.user_id == self.uid, col(SharedExpense.transaction_id).in_(transaction_ids)
            )
        )
        return {row.transaction_id: row for row in rows if row.transaction_id is not None}

    def shares(self, expense_id: UUID) -> builtins.list[ExpenseShare]:
        return list(
            self.db.exec(
                select(ExpenseShare)
                .where(ExpenseShare.user_id == self.uid, ExpenseShare.shared_expense_id == expense_id)
                .order_by(col(ExpenseShare.created), col(ExpenseShare.id))
            )
        )

    def contributions(self, expense_id: UUID) -> builtins.list[ExpenseContribution]:
        return list(
            self.db.exec(
                select(ExpenseContribution)
                .where(ExpenseContribution.user_id == self.uid, ExpenseContribution.shared_expense_id == expense_id)
                .order_by(col(ExpenseContribution.created), col(ExpenseContribution.id))
            )
        )

    def shares_for(self, expense_ids: builtins.list[UUID]) -> dict[UUID, builtins.list[ExpenseShare]]:
        """The shares of many expenses in one query, each list in the order `shares` gives."""
        found: dict[UUID, builtins.list[ExpenseShare]] = {expense_id: [] for expense_id in expense_ids}
        if not expense_ids:
            return found
        rows = self.db.exec(
            select(ExpenseShare)
            .where(ExpenseShare.user_id == self.uid, col(ExpenseShare.shared_expense_id).in_(expense_ids))
            .order_by(col(ExpenseShare.created), col(ExpenseShare.id))
        )
        for row in rows:
            found[row.shared_expense_id].append(row)
        return found

    def contributions_for(self, expense_ids: builtins.list[UUID]) -> dict[UUID, builtins.list[ExpenseContribution]]:
        """Who paid for many expenses in one query, each list in the order `contributions` gives."""
        found: dict[UUID, builtins.list[ExpenseContribution]] = {expense_id: [] for expense_id in expense_ids}
        if not expense_ids:
            return found
        rows = self.db.exec(
            select(ExpenseContribution)
            .where(ExpenseContribution.user_id == self.uid, col(ExpenseContribution.shared_expense_id).in_(expense_ids))
            .order_by(col(ExpenseContribution.created), col(ExpenseContribution.id))
        )
        for row in rows:
            found[row.shared_expense_id].append(row)
        return found

    def shares_of_contact(self, contact_id: UUID) -> dict[UUID, Decimal]:
        """A contact's share of each confirmed expense, by the expense's ledger entry."""
        rows = self.db.exec(
            select(SharedExpense.transaction_id, ExpenseShare.share_amount)
            .join(ExpenseShare, col(ExpenseShare.shared_expense_id) == col(SharedExpense.id))
            .where(
                SharedExpense.user_id == self.uid,
                ExpenseShare.user_id == self.uid,
                SharedExpense.status == "confirmed",
                col(SharedExpense.transaction_id).is_not(None),
                ExpenseShare.contact_id == contact_id,
            )
        )
        return {transaction_id: amount for transaction_id, amount in rows if transaction_id is not None}

    def add(self, expense: SharedExpense) -> SharedExpense:
        self.db.add(expense)
        self.db.flush()
        return expense

    def clear_children(self, expense_id: UUID) -> None:
        for row in (*self.shares(expense_id), *self.contributions(expense_id)):
            self.db.delete(row)
        self.db.flush()

    def delete(self, expense: SharedExpense) -> None:
        self.clear_children(expense.id)
        self.db.delete(expense)
        self.db.flush()

    def uses_contact(self, contact_id: UUID) -> bool:
        """Whether any shared expense, draft or confirmed, names the contact."""
        shares = self.db.exec(
            select(ExpenseShare.id).where(ExpenseShare.user_id == self.uid, ExpenseShare.contact_id == contact_id)
        ).first()
        paid = self.db.exec(
            select(ExpenseContribution.id).where(
                ExpenseContribution.user_id == self.uid, ExpenseContribution.contact_id == contact_id
            )
        ).first()
        return shares is not None or paid is not None

    def uses_account(self, account_id: UUID) -> bool:
        """Whether any shared expense, draft or confirmed, was paid from the account."""
        return (
            self.db.exec(
                select(ExpenseContribution.id).where(
                    ExpenseContribution.user_id == self.uid, ExpenseContribution.account_id == account_id
                )
            ).first()
            is not None
        )

    def repoint_account(self, source: UUID, target: UUID) -> None:
        """What one account paid, another paid (a merge). A bill both paid keeps one row for the two. Nothing is
        committed."""
        rows = list(
            self.db.exec(
                select(ExpenseContribution).where(
                    ExpenseContribution.user_id == self.uid, col(ExpenseContribution.account_id).in_([source, target])
                )
            )
        )
        kept = {row.shared_expense_id: row for row in rows if row.account_id == target}
        for row in rows:
            if row.account_id != source:
                continue
            into = kept.get(row.shared_expense_id)
            if into is None:
                row.account_id = target
                self.db.add(row)
            else:
                into.amount += row.amount
                self.db.add(into)
                self.db.delete(row)
        self.db.flush()

    def uses_category(self, category_id: UUID) -> bool:
        """Whether any shared expense, draft or confirmed, puts the owner's share under the category."""
        return (
            self.db.exec(
                select(SharedExpense.id).where(
                    SharedExpense.user_id == self.uid, SharedExpense.category_id == category_id
                )
            ).first()
            is not None
        )

    def repoint_category(self, source: UUID, target: UUID) -> None:
        """Every shared expense under one category goes under another (a merge). Nothing is committed."""
        self.db.exec(
            update(SharedExpense)
            .where(SharedExpense.user_id == self.uid, SharedExpense.category_id == source)
            .values(category_id=target)
        )
