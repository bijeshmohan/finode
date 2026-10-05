"""Tiny HTML helpers for the web tests (the project has no HTML parsing dependency)."""

from html.parser import HTMLParser


VOID = {"input", "br", "hr", "img", "meta", "link", "option_placeholder"}


class _Finder(HTMLParser):
    def __init__(self, html: str, element_id: str):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.element_id = element_id
        self.lines = [0]
        for line in html.splitlines(keepends=True):
            self.lines.append(self.lines[-1] + len(line))
        self.start = self.end = None
        self.tag = None
        self.depth = 0

    def _offset(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if self.start is None:
            if dict(attrs).get("id") == self.element_id:
                self.start, self.tag, self.depth = self._offset(), tag, 1
                if tag in VOID:
                    self.end = self.start + len(self.get_starttag_text())
        elif self.end is None and tag == self.tag and tag not in VOID:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.start is not None and self.end is None and tag == self.tag:
            self.depth -= 1
            if self.depth == 0:
                self.end = self._offset() + len(f"</{tag}>")


def element(html: str, element_id: str) -> str:
    """The element with this id, tags included."""
    finder = _Finder(html, element_id)
    finder.feed(html)
    assert finder.start is not None and finder.end is not None, f"no element with id '{element_id}'"
    return html[finder.start : finder.end]


class _Options(HTMLParser):
    def __init__(self):
        super().__init__()
        self.options: list[tuple[str, bool, str]] = []
        self._current = None

    def handle_starttag(self, tag, attrs):
        if tag == "option":
            attrs = dict(attrs)
            self._current = [attrs.get("value", ""), "selected" in attrs, ""]

    def handle_data(self, data):
        if self._current is not None:
            self._current[2] += data

    def handle_endtag(self, tag):
        if tag == "option" and self._current is not None:
            value, selected, text = self._current
            self.options.append((value, selected, text.strip()))
            self._current = None


def options(html: str) -> list[tuple[str, bool, str]]:
    """(value, selected, text) of every <option> in the fragment."""
    parser = _Options()
    parser.feed(html)
    return parser.options


def text_of(html: str) -> str:
    class _Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data):
            self.parts.append(data)

    parser = _Text()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())
