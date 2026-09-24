"""Drift guards: the documentation cannot silently disagree with the repository.

Two halves. The first holds the checker itself to account: each rule is shown
to fail on a deliberately broken input, so a green run below means the rule
was applied, not skipped. The second applies the rules to the real docs
(README, CLAUDE.md, SECURITY.md and docs/**):

- every repository path they name exists;
- every `make` target they name is in the Makefile;
- every `sentinel` subcommand they name is in the CLI parser;
- every package under sentinel/ carries a module docstring;
- every headline number registered in tests/doc_claims.toml matches its
  generated source, at the precision the prose states it.

Offline and fast: files are read, nothing is run.
"""

from __future__ import annotations

import pathlib

import pytest

from sentinel.cli import build_parser
from tests.doclint import (
    Claim,
    claim_problems,
    cli_tree,
    commands,
    doc_files,
    load_claims,
    makefile_targets,
    missing_paths,
    parse_markdown,
    undocumented_packages,
    unknown_cli_commands,
    unknown_make_targets,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The trace names planned evidence before it exists, by design, and reports it
# as unverified. Its generator checks every reference it makes, and fails on a
# broken one (tests/mbse/test_real_model.py), so its paths are not checked twice.
PATHS_CHECKED_BY_GENERATOR = {"docs/traceability.md"}


def _id(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


DOCS = doc_files(ROOT)
PATH_DOCS = [d for d in DOCS if _id(d) not in PATHS_CHECKED_BY_GENERATOR]
CLAIMS = load_claims(ROOT / "tests" / "doc_claims.toml")
MAKE_TARGETS = makefile_targets((ROOT / "Makefile").read_text(encoding="utf-8"))
CLI = cli_tree(build_parser())


# --- the checker, on deliberately broken inputs ------------------------------


def _write(root: pathlib.Path, relative: str, text: str = "") -> pathlib.Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A miniature repository: two docs, one script, one image."""
    _write(tmp_path, "docs/guide.md")
    _write(tmp_path, "docs/img/plot.png")
    _write(tmp_path, "scripts/run.py")
    return tmp_path


def test_a_backticked_path_that_does_not_exist_is_reported(repo):
    md = parse_markdown("Run `scripts/run.py`, then read `docs/gone.md` and `docs/guide.md`.")
    assert missing_paths(md, repo / "docs", repo) == ["docs/gone.md"]


def test_a_path_inside_a_fenced_command_is_checked(repo):
    md = parse_markdown("```bash\nuv run python scripts/renamed.py   # writes docs/guide.md\n```\n")
    assert missing_paths(md, repo / "docs", repo) == ["scripts/renamed.py"]


def test_a_broken_relative_link_or_image_is_reported(repo):
    text = "[guide](guide.md#top) ![plot](img/plot.png) ![old](img/old.png) [up](../nowhere.md)"
    assert missing_paths(parse_markdown(text), repo / "docs", repo) == ["img/old.png", "../nowhere.md"]


def test_things_that_are_not_repository_paths_are_left_alone(repo):
    _write(repo, "dist/sentinel.tar.gz")  # a local build output is still not part of the repository
    text = (
        "`https://example.org/docs/x`, `/api/health`, `node.<id>.>`, `dist/sbom/`, "
        "`.tools/x86_64/cosign`, `x/crypto/openpgp`, `$TUF_ROOT/docs/x`, `docs/<name>.md`, "
        "[site](https://example.org) [anchor](#here)"
    )
    assert missing_paths(parse_markdown(text), repo / "docs", repo) == []


def test_a_glob_must_match_something_and_a_test_id_names_its_file(repo):
    md = parse_markdown(
        "`scripts/*.py`, `scripts/*.sh`, `scripts/run.py::test_x`, `scripts/run.py:12`, "
        "`scripts/run.py:main`, `scripts/gone.py:main`"
    )
    assert missing_paths(md, repo / "docs", repo) == ["scripts/*.sh", "scripts/gone.py"]


def test_a_make_target_that_is_not_in_the_makefile_is_reported():
    makefile = "all: build  ## x\nbuild:\n\techo hi\nVAR := 1\nOTHER ?= a:b\n"
    md = parse_markdown("`make build`, then\n```\nmake all deploy VAR=2 && make build  # make nothing\n```\n")
    assert makefile_targets(makefile) == {"all", "build"}
    assert unknown_make_targets(commands(md), makefile_targets(makefile)) == ["deploy"]


def test_a_cli_subcommand_that_does_not_exist_is_reported():
    md = parse_markdown(
        "`sentinel assess X.cdm`, `uv run sentinel cdm parse X`, `sentinel cdm lint X`, "
        "`SENTINEL_X=1 sentinel launch`, `sentinel --help`, `systemctl status sentinel`"
    )
    assert unknown_cli_commands(commands(md), CLI) == ["cdm lint", "launch"]


def test_a_package_without_a_docstring_is_reported(tmp_path):
    _write(tmp_path, "pkg/__init__.py", '"""Documented."""\n')
    _write(tmp_path, "pkg/bare/__init__.py", "from x import y\n")
    _write(tmp_path, "pkg/loose/module.py", '"""A module in a directory with no __init__.py."""\n')
    assert undocumented_packages(tmp_path / "pkg") == ["pkg/bare", "pkg/loose"]


def test_a_claim_fails_when_the_source_number_moves(tmp_path):
    _write(tmp_path, "README.md", "The record arrives in 5.5 s vs 38.2 s in FIFO order.")
    _write(tmp_path, "report.md", "EDF 5.1 s vs FIFO 38.2 s")
    claim = Claim("edf", "README.md", "5.5 s vs 38.2 s", "report.md", ("EDF 5.5 s vs FIFO 38.2 s",))
    assert claim_problems(claim, tmp_path) == ["report.md no longer says 'EDF 5.5 s vs FIFO 38.2 s'"]


def test_a_claim_fails_when_the_prose_moves(tmp_path):
    _write(tmp_path, "README.md", "The record arrives in 5.1 s.")
    _write(tmp_path, "report.md", "EDF 5.5 s")
    claim = Claim("edf", "README.md", "5.5 s", "report.md", ("EDF 5.5 s",))
    assert claim_problems(claim, tmp_path) == ["README.md no longer says '5.5 s'"]


def test_a_claim_fails_when_its_quote_states_a_number_its_source_does_not(tmp_path):
    _write(tmp_path, "README.md", "The record arrives in 5.1 s, about 8x sooner.")
    _write(tmp_path, "report.md", "EDF 5.5 s (6.9x)")
    claim = Claim("edf", "README.md", "5.1 s, about 8x", "report.md", ("EDF 5.5 s (6.9x)",))
    assert claim_problems(claim, tmp_path) == ["'5.1 s, about 8x' states 5.1, 8, which report.md does not"]


def test_a_claim_is_matched_across_line_breaks_and_at_the_precision_stated(tmp_path):
    _write(tmp_path, "README.md", "worst relative\nerror **5.2e-07** and 1.5e-8")
    _write(tmp_path, "report.md", "Worst relative error: **5.16e-07**, then 1.5e-08")
    claim = Claim("k", "README.md", "worst relative error **5.2e-07** and 1.5e-8", "report.md",
                  ("Worst relative error: **5.16e-07**", "1.5e-08"))
    assert claim_problems(claim, tmp_path) == []


def test_a_quoted_digest_must_match_its_pin_verbatim(tmp_path):
    pinned = "4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71"
    stale = "0000c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71"
    _write(tmp_path, "guide.md", f'echo "{stale}  cosign" and cosign 3.1.3')
    _write(tmp_path, "tools.lock", f"cosign 3.1.3 x86_64 {pinned}")
    claim = Claim("pin", "guide.md", f'echo "{stale}  cosign" and cosign 3.1.3', "tools.lock",
                  (f"cosign 3.1.3 x86_64 {pinned}",))
    assert claim_problems(claim, tmp_path) == [
        f"'echo \"{stale}  cosign\" and cosign 3.1.3' states {stale}, which tools.lock does not"
    ]


def test_a_claim_without_a_number_is_rejected(tmp_path):
    _write(tmp_path, "README.md", "about half")
    _write(tmp_path, "report.md", "about half")
    claim = Claim("vague", "README.md", "about half", "report.md", ("about half",))
    assert claim_problems(claim, tmp_path) == ["'about half' states no number to check"]


# --- the real documentation ---------------------------------------------------


def test_the_doc_set_covers_the_readme_the_rules_and_the_design_docs():
    names = {_id(d) for d in DOCS}
    assert {"README.md", "CLAUDE.md", "SECURITY.md", "docs/system-design.md"} <= names
    assert {"docs/adapters/wayfinder.md", "docs/validation-report.md", "fixtures/README.md"} <= names


def test_the_fixtures_readme_names_every_fixture():
    """A new fixture gets a line in the README; a removed one takes its line with it
    (the path check above)."""
    named = set(parse_markdown((ROOT / "fixtures" / "README.md").read_text(encoding="utf-8")).code)
    entries = sorted((ROOT / "fixtures").iterdir())
    paths = [f"fixtures/{e.name}/" if e.is_dir() else f"fixtures/{e.name}" for e in entries if e.name != "README.md"]
    assert [p for p in paths if p not in named] == []


@pytest.mark.parametrize("doc", PATH_DOCS, ids=_id)
def test_every_path_a_doc_names_exists(doc):
    md = parse_markdown(doc.read_text(encoding="utf-8"))
    assert missing_paths(md, doc.parent, ROOT) == []


@pytest.mark.parametrize("doc", DOCS, ids=_id)
def test_every_make_target_a_doc_names_exists(doc):
    md = parse_markdown(doc.read_text(encoding="utf-8"))
    assert unknown_make_targets(commands(md), MAKE_TARGETS) == []


@pytest.mark.parametrize("doc", DOCS, ids=_id)
def test_every_cli_subcommand_a_doc_names_exists(doc):
    md = parse_markdown(doc.read_text(encoding="utf-8"))
    assert unknown_cli_commands(commands(md), CLI) == []


def test_every_package_has_a_module_docstring():
    assert undocumented_packages(ROOT / "sentinel") == []


def test_the_claims_registry_covers_the_headline_numbers():
    sources = {claim.source for claim in CLAIMS}
    assert {
        "docs/ddil-results.md",
        "docs/validation-report.md",
        "docs/ai-eval.md",
        "docs/traceability.md",
    } <= sources
    assert len({claim.id for claim in CLAIMS}) == len(CLAIMS), "claim ids must be unique"


@pytest.mark.parametrize("claim", CLAIMS, ids=[c.id for c in CLAIMS])
def test_every_quoted_number_matches_its_source(claim):
    assert claim_problems(claim, ROOT) == []
