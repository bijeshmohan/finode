"""The version in pyproject.toml, for the feedback email (so a report says which build it is about)."""

import tomllib
from pathlib import Path


def _read() -> str:
    try:
        with (Path(__file__).resolve().parent.parent / "pyproject.toml").open("rb") as f:
            return str(tomllib.load(f)["project"]["version"])
    except OSError, KeyError, tomllib.TOMLDecodeError:
        return "unknown"


VERSION = _read()
