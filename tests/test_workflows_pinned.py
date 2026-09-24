"""Every third-party action in every workflow is pinned by full commit SHA.

A tag like `@v4` can be moved to different code after review; a commit SHA
cannot (NIST SR-3, SR-11). Local actions (`./...`) are part of this repo.
"""

import pathlib
import re

WORKFLOWS = sorted((pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
PINNED = re.compile(r"@[0-9a-f]{40}$")


def unpinned(paths=WORKFLOWS) -> list[str]:
    found = []
    for path in paths:
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            match = USES.match(line)
            if match and not match.group(1).startswith("./") and not PINNED.search(match.group(1)):
                found.append(f"{path.name}:{number} {match.group(1)}")
    return found


def test_every_action_is_pinned_by_commit_sha():
    assert WORKFLOWS, "the workflows exist"
    assert unpinned() == []


def test_the_check_catches_a_tag(tmp_path):
    workflow = tmp_path / "x.yml"
    workflow.write_text("steps:\n  - uses: actions/checkout@v4\n  - uses: ./local\n")
    assert unpinned([workflow]) == ["x.yml:2 actions/checkout@v4"]


def unlocked_installs(paths=WORKFLOWS) -> list[str]:
    """Python installs that resolve fresh instead of installing uv.lock."""
    found = []
    for path in paths:
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if re.search(r"\b(uv pip install|pip install)\b", line):
                found.append(f"{path.name}:{number} {line.strip()}")
    return found


def test_python_dependencies_install_from_the_lock():
    """CI installs exactly uv.lock (`uv sync --locked`), so a new upstream
    release cannot change what CI tests, and a stale lock fails."""
    assert unlocked_installs() == []
    for path in WORKFLOWS:
        text = path.read_text()
        if "setup-uv@" in text:
            assert "uv sync --locked" in text, path.name


def test_the_lock_check_catches_a_fresh_resolve(tmp_path):
    workflow = tmp_path / "x.yml"
    workflow.write_text("steps:\n  - run: uv pip install -e \".[dev]\"\n")
    assert unlocked_installs([workflow]) == ['x.yml:2 - run: uv pip install -e ".[dev]"']
