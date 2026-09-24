"""`.env.example` is committed, and the `.env` filled in from it never is.

It names every variable hosted AI reads, empty, each under a one-line
comment. `make ai-live-check` points at it when a key is not set.
"""

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / ".env.example"
VARIABLES = {"TYPESAFE_API_KEY": "", "ANTHROPIC_API_KEY": "", "SENTINEL_AI_CLOUD": "0"}


def ignored(path: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0


def test_the_template_lists_each_variable_under_a_comment_with_no_value():
    lines = TEMPLATE.read_text().splitlines()
    assignments = {i: m for i, line in enumerate(lines) if (m := re.fullmatch(r"([A-Z_]+)=(.*)", line))}
    assert {m[1]: m[2] for m in assignments.values()} == VARIABLES, "no key value is ever committed"
    for i, m in assignments.items():
        assert lines[i - 1].startswith("# "), f"{m[1]} has no comment line above it"


def test_the_filled_in_copy_is_ignored_and_the_template_is_not():
    assert ignored(".env")
    assert not ignored(".env.example")
