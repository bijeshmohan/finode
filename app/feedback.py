"""The "Send feedback" link: a mailto that starts an email to whoever runs finode (no personal data in it)."""

from urllib.parse import quote

from .config import settings
from .version import VERSION


def feedback_url() -> str | None:
    if not settings.feedback_email:
        return None
    body = f"What happened, or what would help?\n\n\n\n--\nfinode {VERSION}"
    return f"mailto:{settings.feedback_email}?subject={quote('finode feedback')}&body={quote(body)}"
