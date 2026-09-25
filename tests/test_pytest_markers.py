"""Every pytest marker pyproject.toml declares is one a test uses.

A declared marker reads as a convention the suite follows. One nothing uses
misleads: `req(id)` claimed tests were linked to requirements by marker,
while that mapping lives in mbse/verification.sysml.
"""

import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARK = re.compile(r"\bmark\.(\w+)")


def declared(pyproject: str) -> set[str]:
    """Marker names from [tool.pytest.ini_options] markers ("name(args): help")."""
    lines = tomllib.loads(pyproject)["tool"]["pytest"]["ini_options"].get("markers", [])
    return {re.split(r"[(:]", line, maxsplit=1)[0].strip() for line in lines}


def used(sources: list[str]) -> set[str]:
    return {name for source in sources for name in MARK.findall(source)}


def test_every_declared_marker_is_used():
    this = pathlib.Path(__file__).resolve()  # its examples below use markers only as text
    tests = sorted(p for p in (ROOT / "tests").rglob("*.py") if p.resolve() != this)
    sources = [path.read_text(encoding="utf-8") for path in tests]
    assert sorted(declared((ROOT / "pyproject.toml").read_text(encoding="utf-8")) - used(sources)) == []


def test_an_unused_marker_is_caught():
    pyproject = '[tool.pytest.ini_options]\nmarkers = ["tier1: geometry", "req(id): a requirement"]\n'
    assert declared(pyproject) == {"tier1", "req"}
    assert declared(pyproject) - used(["pytestmark = pytest.mark.tier1\n"]) == {"req"}
