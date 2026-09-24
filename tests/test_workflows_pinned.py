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
