"""Finding categories by the names people (and assistants) use for them."""

import difflib
import re
from uuid import UUID

from ..schemas.category import CategoryRead

SEPARATORS = re.compile(r"\s*(?::|›|>|/)\s*")


class CategoryIndex:
    def __init__(self, categories: list[CategoryRead]):
        self.categories = {c.id: c for c in categories}

    def path(self, category_id: UUID | None) -> str | None:
        category = self.categories.get(category_id) if category_id else None
        return category.path if category else None

    def find(self, text: str, *, kind: str | None = None, open_only: bool = False) -> CategoryRead:
        """The one category `text` names: its id, its path ("Food:Groceries") or the end of one ("Groceries").
        Raises ValueError naming the choices when it is not one."""
        text = (text or "").strip()
        if not text:
            raise ValueError("a category is required: give its path, for example Food:Groceries!")
        try:
            by_id = self.categories.get(UUID(text))
        except ValueError:
            by_id = None
        candidates = list(self.categories.values())
        if by_id is not None:
            return self._check(by_id, kind, open_only)
        wanted = [s.casefold() for s in SEPARATORS.split(text) if s]

        def folded(category: CategoryRead) -> list[str]:
            return [s.casefold() for s in category.path.split(":")]

        exact = [c for c in candidates if folded(c) == wanted]
        matches = exact or [c for c in candidates if folded(c)[-len(wanted) :] == wanted]
        if len(matches) > 1 and kind is not None:
            matches = [c for c in matches if c.kind == kind] or matches
        if len(matches) > 1:
            matches = [c for c in matches if c.closed_on is None] or matches
        if len(matches) == 1:
            return self._check(matches[0], kind, open_only)
        if matches:
            listed = ", ".join(sorted(c.path for c in matches))
            raise ValueError(f"'{text}' matches {len(matches)} categories: {listed}. Use the full path!")
        paths = [c.path for c in candidates]
        close = difflib.get_close_matches(text, paths, n=3, cutoff=0.5)
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        raise ValueError(f"no category matches '{text}'.{hint} Call list_categories to see them all.")

    @staticmethod
    def _check(category: CategoryRead, kind: str | None, open_only: bool) -> CategoryRead:
        if kind is not None and category.kind != kind:
            article = "an" if category.kind == "earning" else "a"
            raise ValueError(f"'{category.path}' is {article} {category.kind} category, not a {kind} one!")
        if open_only and category.closed_on is not None:
            raise ValueError(f"'{category.path}' is closed: the user can reopen it in finode to use it!")
        return category
