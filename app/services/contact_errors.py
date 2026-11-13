"""What can go wrong with contacts, expense sharing and settlements. All are `ValueError`s with a message that is safe
to show; the routers answer 404 for the "not found" ones, 409 for a conflict and 400 for the rest."""


class NotFoundError(ValueError):
    """What was asked for is not among the person's own (HTTP 404)."""


class ContactNotFoundError(NotFoundError):
    """No such contact among the person's own."""

    def __init__(self) -> None:
        super().__init__("contact not found!")


class ContactArchivedError(ValueError):
    """The contact is archived: restore it before using it again."""


class ContactInUseError(ValueError):
    """The contact cannot be archived or removed because something is still owed."""


class InvalidContactAccountError(ValueError):
    """The account named is not one the operation can use (a contact's own account, or not yours)."""


class InvalidTransferPurposeError(ValueError):
    """The purpose does not fit the direction (a loan is money sent, a borrowing money received)."""


class ObligationNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("obligation not found!")


class InsufficientOutstandingBalanceError(ValueError):
    """More was asked of an obligation than is still owed on it."""


class ObligationAlreadySettledError(ValueError):
    """The obligation has nothing left to settle."""


class InvalidSettlementAllocationError(ValueError):
    """The settlement's allocations do not fit the obligations or the amount."""


class InvalidExpenseAllocationError(ValueError):
    """The shares of a shared expense are wrong (they do not add up, a participant is repeated…)."""


class InvalidExpenseContributionError(ValueError):
    """Who paid for a shared expense is wrong (the payments do not add up to the total…)."""


class SharedExpenseNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("shared expense not found!")


class ConflictError(ValueError):
    """The request clashes with what was already done (HTTP 409)."""


class SharedExpenseAlreadyConfirmedError(ConflictError):
    """A confirmed shared expense is not edited or confirmed again; cancel it to start over."""


class DuplicateRequestError(ConflictError):
    """An idempotency key was already used for a different request."""


class ReversalBlockedError(ConflictError):
    """Something was settled against the entry, so it cannot be reversed until that is reversed first."""


class InvalidSharedIncomeError(ValueError):
    """Income shared with people is wrong (the parts or the deposits do not add up, a person is on both sides…)."""


class SharedIncomeNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("shared income not found!")
