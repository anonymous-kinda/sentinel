"""The version a release is built from is the one its documents name.

`sentinel.__version__` names the bundles (`sentinel-<VER>-<arch>`). The
install commands the docs show must use it, and CHANGELOG.md must say what
it contains, or an operator copies a command for a bundle that does not exist.
"""

import pathlib
import re

import pytest

from sentinel import __version__

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL_DOCS = ["docs/install-guide.md", "docs/supply-chain.md"]


@pytest.mark.parametrize("doc", INSTALL_DOCS)
def test_every_install_command_names_the_current_version(doc):
    versions = set(re.findall(r"\bVER=([0-9][0-9A-Za-z.\-]*)", (ROOT / doc).read_text()))
    assert versions == {__version__}


def test_the_changelog_says_what_the_current_version_contains():
    changelog = (ROOT / "CHANGELOG.md").read_text()
    newest = re.search(r"^## \[([^\]]+)\]", changelog, re.MULTILINE)
    assert newest, "CHANGELOG.md has no version heading"
    assert newest[1] == __version__
