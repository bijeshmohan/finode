"""Tags are #hashtags written in a transaction's note ("Dinner with Ravi #reimbursable #goa-trip").

Nothing is stored for them: the note is the one place, so tags work the same on the web form, the API, imports and
backups, and for assistants. A tag is a # that starts a word, then 1 to 30 letters, digits, `-` or `_` (it starts and
ends with a letter or digit), is read case-insensitively, and has at least one letter, so "#1" is not a tag.
"""

import re

MAX_TAG = 30

_TAG = re.compile(rf"(?<!\S)#([A-Za-z0-9](?:[A-Za-z0-9_-]{{0,{MAX_TAG - 2}}}[A-Za-z0-9])?)(?![A-Za-z0-9])")


def tags_in(note: str | None) -> list[str]:
    """The tags in a note, lower-case, each once, in the order they first appear."""
    found: list[str] = []
    for match in _TAG.finditer(note or ""):
        tag = match.group(1).lower()
        if any(c.isalpha() for c in tag) and tag not in found:
            found.append(tag)
    return found


def clean_tag(value: str) -> str:
    """A tag as typed by someone searching ("#Goa-Trip", " goa-trip "): the bare lower-case name."""
    return value.strip().lstrip("#").strip().lower()


def without_tags(note: str | None) -> str:
    """The note with its tags taken out, for places that show the tags apart from the words ("Dinner #goa-trip" -> "Dinner")."""
    kept = note or ""
    for match in reversed(list(_TAG.finditer(kept))):
        if any(c.isalpha() for c in match.group(1)):
            kept = kept[: match.start()] + kept[match.end() :]
    return " ".join(kept.split())
