"""Policy: the pass module never calls a gap "safe".

A gap means only that no catalogued imager, under stated planning
assumptions, has the unit in its field of regard. Uncatalogued imagers,
aircraft and ground sensors are not counted, so the word would overclaim.
This parses the source rather than trusting review: labels, docstrings and
the catalog's basis text are all checked.
"""

import ast
import pathlib
import re

from sentinel.passes.catalog import DEFAULT_CATALOG, load_catalog
from sentinel.passes.gaps import GAP_LABEL, Gap

PASSES = pathlib.Path(__file__).resolve().parents[2] / "sentinel" / "passes"
OVERCLAIM = re.compile(r"\bsafe", re.IGNORECASE)      # safe, safely, safety, safer


def exposed_text(path: pathlib.Path) -> list[tuple[int, str]]:
    """Docstrings, plus every string constant bound to a module-level name."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            docstring = ast.get_docstring(node)
            if docstring:
                found.append((getattr(node, "lineno", 1), docstring))
    for node in tree.body:
        value = getattr(node, "value", None)
        if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(value, ast.Constant) and isinstance(value.value, str):
            found.append((node.lineno, value.value))
    return found


def test_the_gap_label_says_what_it_means_and_no_more():
    assert GAP_LABEL == "not observed by catalogued imagers"
    assert Gap.__dataclass_fields__["label"].default == GAP_LABEL
    assert not OVERCLAIM.search(GAP_LABEL)


def test_no_docstring_or_label_in_the_pass_module_says_safe():
    offending = [
        f"{path.relative_to(PASSES.parent)}:{line}"
        for path in sorted(PASSES.rglob("*.py"))
        for line, text in exposed_text(path)
        if OVERCLAIM.search(text)
    ]
    assert offending == []


def test_no_catalog_basis_says_safe():
    assert DEFAULT_CATALOG.parent == PASSES
    assert [i.name for i in load_catalog() if OVERCLAIM.search(i.basis)] == []


def test_the_policy_check_itself_would_catch_the_word(tmp_path):
    """Guard against a vacuous scan."""
    sample = tmp_path / "sample.py"
    sample.write_text('"""Module."""\nLABEL = "Safe to move"\n\ndef f():\n    """Now safely hidden."""\n')
    assert [text for _, text in exposed_text(sample) if OVERCLAIM.search(text)] == ["Now safely hidden.", "Safe to move"]
