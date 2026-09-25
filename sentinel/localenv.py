"""Local keys and opt-ins for development commands: the gitignored `.env`.

`make ai-live-check`, `make ai-eval` and `make demo-local` read it, so a key
is written once, in one file (`.env.example` is its template). A variable
already set in the environment wins, and an empty value sets nothing, so the
file never hides a key exported in the shell. A deployed node does not read
it: systemd passes its own environment file.

Values are never logged; the names loaded are.
"""

from __future__ import annotations

import os
import pathlib
import re
from collections.abc import MutableMapping

from .obs import get_logger

log = get_logger(__name__)

DEFAULT_PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"
_ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)")


def load(path: pathlib.Path = DEFAULT_PATH, environ: MutableMapping[str, str] = os.environ) -> list[str]:
    """Set each non-empty variable in `path` that `environ` lacks; return their names."""
    if not path.is_file():
        return []
    loaded = []
    for name, value in _assignments(path.read_text()):
        if value and not environ.get(name):
            environ[name] = value
            loaded.append(name)
    if loaded:
        log.info("Local env file loaded", path=str(path), names=loaded)
    return loaded


def _assignments(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.fullmatch(line)
        if match:
            pairs.append((match[1], _unquoted(match[2].strip())))
    return pairs


def _unquoted(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value
