"""docs/icd/README.md indexes every interface control document, only those
that exist, and names checks that exist."""

from .icd import ICD, ROOT, backticked, column, compare, drop_row, table_rows

INDEX = ICD / "README.md"


def present() -> set[str]:
    return {path.name for path in ICD.iterdir() if path.is_file() and path.name != INDEX.name}


def index_problems(doc: str) -> list[str]:
    problems = compare(column(doc, "Documents"), present(), "ICD")
    for _document, *_, kept_current in table_rows(doc, "Documents"):
        problems += [f"{p} does not exist" for p in backticked(kept_current) if "/" in p and not (ROOT / p).exists()]
    return problems


def test_the_index_lists_every_icd_and_its_checks_exist():
    assert index_problems(INDEX.read_text()) == []


def test_a_stale_index_is_caught():
    doc = INDEX.read_text()
    assert index_problems(drop_row(doc, "asyncapi.yaml")) == ["ICD asyncapi.yaml is not documented"]
    moved = doc.replace("`tests/docs/test_cdm_profile.py`", "`tests/test_cdm_profile.py`", 1)
    assert index_problems(moved) == ["tests/test_cdm_profile.py does not exist"]
