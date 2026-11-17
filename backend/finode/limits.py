"""How much one person may hold, so one account cannot fill the shared database (see the `max_*` settings)."""

from .config import settings


class LimitReached(ValueError):
    """A per-person limit was hit; the message says what to do about it and is safe to show."""


def ensure_room(count: int, limit: int, what: str, adding: int = 1) -> None:
    """Refuse when `adding` more would take someone past `limit` (0 means no limit)."""
    if limit and count + adding > limit:
        raise LimitReached(
            f"you have reached the limit of {limit:,} {what}. Delete or close some you no longer need, "
            "or ask the person who runs finode to raise it!"
        )


def upload_limit_bytes(megabytes: int) -> int:
    return megabytes * 1024 * 1024


__all__ = ["LimitReached", "ensure_room", "settings", "upload_limit_bytes"]
