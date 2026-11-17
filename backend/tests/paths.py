"""Where the repository's files are, for the tests that read them (the API's own docs, compose.yaml, the app's files)."""

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
