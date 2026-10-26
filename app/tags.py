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


# What a tag is once it is its own thing (not read out of a note): the same letters as before, kept exactly.
MAX_TAGS_PER_ENTRY = 10
_NAME = re.compile(rf"[A-Za-z0-9](?:[A-Za-z0-9_-]{{0,{MAX_TAG - 2}}}[A-Za-z0-9])?")


def clean_name(value: str) -> str:
    """A tag as a person or an assistant gives it, made into its one form: no #, no spaces, lower case. Raises ValueError
    for something that cannot be a tag (too long, odd characters, no letter)."""
    name = clean_tag(value)
    if not _NAME.fullmatch(name) or not any(c.isalpha() for c in name):
        raise ValueError(
            f"'{value.strip()}' cannot be a tag: use 1 to {MAX_TAG} letters, digits, - or _ (at least one letter)!"
        )
    return name


def clean_names(values: list[str] | None) -> list[str]:
    """A list of tags made into their one form, each once, in the order given; at most MAX_TAGS_PER_ENTRY."""
    names: list[str] = []
    for value in values or []:
        name = clean_name(value)
        if name not in names:
            names.append(name)
    if len(names) > MAX_TAGS_PER_ENTRY:
        raise ValueError(f"an entry can have at most {MAX_TAGS_PER_ENTRY} tags!")
    return names


# A tag right after one of these words is part of the sentence ("paid through #UPI").
_CONNECTORS = frozenset(
    [
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "per",
        "the",
        "through",
        "to",
        "using",
        "via",
        "with",
    ]
)


def split_note(note: str | None) -> tuple[str | None, list[str]]:
    """An old note split into (its words, its #tags), for files written when tags lived in the note (backups before
    version 3). A tag that is part of the sentence ("paid through #UPI") keeps its word in the words, without the #.
    A note with more tags than an entry may have is left exactly as it is."""
    names = tags_in(note)
    if not names or len(names) > MAX_TAGS_PER_ENTRY:
        return note, []
    kept = note or ""
    for match in reversed([m for m in _TAG.finditer(kept) if any(c.isalpha() for c in m.group(1))]):
        before = kept[: match.start()].split()
        word = match.group(1) if before and before[-1].lower() in _CONNECTORS else ""
        kept = kept[: match.start()] + word + kept[match.end() :]
    return " ".join(kept.split()) or None, names
