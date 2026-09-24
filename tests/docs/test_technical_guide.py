"""The engineer-facing docs, checked against the repository they describe.

Documentation written from memory drifts. These checks hold
docs/technical-guide.md, docs/index.md and CONTRIBUTING.md to the code:

  variables  every SENTINEL_* variable the code reads has a row in the
             guide's configuration reference, and every SENTINEL_* name
             the docs mention is one the code reads
  make, CLI  every `make` target and `sentinel` subcommand the docs show exists
  contracts  the guide's table quotes every .importlinter contract, module by module
  paths      every repository path the docs name exists
  index      every Markdown document in the repository is listed in the index

Paths, make targets and CLI subcommands use the rules in tests/doclint.py,
which tests/test_docs.py applies to docs/**; here they cover CONTRIBUTING.md
too. Each check also runs against a deliberately stale copy, to show it
would catch the drift rather than pass by accident.
"""

import ast
import configparser
import pathlib
import re
import subprocess

import pytest

from sentinel.cli import build_parser
from tests.doclint import (
    cli_tree,
    commands,
    makefile_targets,
    missing_paths,
    parse_markdown,
    unknown_cli_commands,
    unknown_make_targets,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
GUIDE = "docs/technical-guide.md"
INDEX = "docs/index.md"
DOCS = (GUIDE, INDEX, "CONTRIBUTING.md")

VARIABLE = re.compile(r"\bSENTINEL_[A-Z0-9_]+\b")
PYTHON_CODE = ("sentinel", "harness", "scripts", "supplychain", "compliance", "mbse")
SHELL_CODE = ("deploy",)
REFERENCE = "Configuration reference"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


# ------------------------------------------------------------- variables
def python_reads(source: str) -> set[str]:
    """SENTINEL_* names a module reads: the first argument of a call
    (os.environ.get, os.getenv, a flag helper) or an os.environ[...] key."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        key = node.args[0] if isinstance(node, ast.Call) and node.args else None
        if isinstance(node, ast.Subscript):
            key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and VARIABLE.fullmatch(key.value):
            names.add(key.value)
    return names


def shell_reads(source: str) -> set[str]:
    """SENTINEL_* names a shell script expands ($NAME or ${NAME...}), comments excluded."""
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    return set(re.findall(r"\$\{?(SENTINEL_[A-Z0-9_]+)", code))


def code_reads() -> set[str]:
    names = set()
    for top in PYTHON_CODE:
        for path in sorted((ROOT / top).rglob("*.py")):
            names |= python_reads(path.read_text(encoding="utf-8"))
    for top in SHELL_CODE:
        for path in sorted((ROOT / top).rglob("*.sh")):
            names |= shell_reads(path.read_text(encoding="utf-8"))
    return names


def section(markdown: str, heading: str) -> str:
    """The body of a `## heading` section, up to the next level-2 heading."""
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", markdown, re.M | re.S)
    return match.group(1) if match else ""


def documented_variables(markdown: str) -> set[str]:
    """Variables with their own row in the configuration reference tables."""
    return set(re.findall(r"^\|\s*`(SENTINEL_[A-Z0-9_]+)`", section(markdown, REFERENCE), re.M))


def mentioned_variables(markdown: str) -> set[str]:
    return set(VARIABLE.findall(markdown))


def test_the_code_reads_the_variables_this_test_expects_to_find():
    reads = code_reads()
    assert {"SENTINEL_NODE_ID", "SENTINEL_AI_CLOUD", "SENTINEL_CLOCK", "SENTINEL_LOG_LEVEL"} <= reads
    assert {"SENTINEL_FIXTURES", "SENTINEL_VERIFY_KEY", "SENTINEL_CERT_ISSUER"} <= reads
    assert python_reads('os.environ["SENTINEL_X"]\nflag("SENTINEL_Y", True)\nprint("SENTINEL-Z")') == {
        "SENTINEL_X",
        "SENTINEL_Y",
    }
    assert shell_reads('# ${SENTINEL_A}\nKEY=${SENTINEL_B:-}\n[[ -n "$SENTINEL_C" ]]\nenv -u SENTINEL_D') == {
        "SENTINEL_B",
        "SENTINEL_C",
    }


def test_every_variable_the_code_reads_is_in_the_configuration_reference():
    guide = read(GUIDE)
    assert sorted(code_reads() - documented_variables(guide)) == []

    row = next(line for line in guide.splitlines() if line.startswith("| `SENTINEL_CLOCK`"))
    stale = guide.replace(row + "\n", "")
    assert sorted(code_reads() - documented_variables(stale)) == ["SENTINEL_CLOCK"]


@pytest.mark.parametrize("doc", DOCS)
def test_every_variable_the_docs_name_is_read_by_the_code(doc):
    text = read(doc)
    assert sorted(mentioned_variables(text) - code_reads()) == []

    stale = text + "\n| `SENTINEL_TURBO` | `0` | Makes everything faster. |\n"
    assert sorted(mentioned_variables(stale) - code_reads()) == ["SENTINEL_TURBO"]


# ----------------------------------------------------- make and the CLI
# The same rules tests/test_docs.py applies to docs/**, applied here to all
# three files: CONTRIBUTING.md sits outside that guard's document set.
MAKE_TARGETS = makefile_targets(read("Makefile"))
CLI = cli_tree(build_parser())


def unknown_targets(markdown: str) -> list[str]:
    return unknown_make_targets(commands(parse_markdown(markdown)), MAKE_TARGETS)


def mentioned_targets(markdown: str) -> set[str]:
    named = set()
    for argv in commands(parse_markdown(markdown)):
        if argv[0] == "make":
            named |= {word for word in argv[1:] if "=" not in word and not word.startswith("-")}
    return named


@pytest.mark.parametrize("doc", DOCS)
def test_every_make_target_the_docs_mention_exists(doc):
    text = read(doc)
    assert unknown_targets(text) == []
    assert unknown_targets(text + "\n\n`make deploy-everything`\n") == ["deploy-everything"]


@pytest.mark.parametrize("doc", DOCS)
def test_every_cli_subcommand_the_docs_mention_exists(doc):
    text = read(doc)
    assert unknown_cli_commands(commands(parse_markdown(text)), CLI) == []
    stale = text + "\n\n`uv run sentinel cdm lint X.cdm`\n"
    assert unknown_cli_commands(commands(parse_markdown(stale)), CLI) == ["cdm lint"]


def test_the_guide_shows_the_everyday_targets():
    everyday = {"serve", "test", "lint", "trace", "ddil", "opsec", "demo-local", "airgap-local"}
    assert sorted(everyday - mentioned_targets(read(GUIDE))) == []


# -------------------------------------------------------- import contracts
def contracts(importlinter: str) -> dict[str, list[str]]:
    """Contract id -> every module it names (sources and forbidden)."""
    parser = configparser.ConfigParser()
    parser.read_string(importlinter)
    prefix = "importlinter:contract:"
    return {
        name.removeprefix(prefix): parser[name].get("source_modules", "").split()
        + parser[name].get("forbidden_modules", "").split()
        for name in parser.sections()
        if name.startswith(prefix)
    }


def misquoted(guide: str, importlinter: str) -> list[str]:
    """`id: module` for every module a contract names that its row in the guide does not."""
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `([a-z0-9-]+)` \|.*$", guide, re.M)}
    problems = []
    for contract_id, modules in sorted(contracts(importlinter).items()):
        row = rows.get(contract_id)
        if row is None:
            problems.append(f"{contract_id}: no row")
            continue
        problems += [f"{contract_id}: {m}" for m in modules if not re.search(rf"(?<![\w.]){re.escape(m)}(?![\w.])", row)]
    return problems


def test_the_guide_quotes_every_import_contract_module_by_module():
    importlinter, guide = read(".importlinter"), read(GUIDE)
    assert len(contracts(importlinter)) >= 11
    assert misquoted(guide, importlinter) == []

    header = "source_modules =\n    sentinel.bus\n    sentinel.triage\nforbidden_modules =\n"
    assert header in importlinter
    widened = importlinter.replace(header, header + "    sentinel.screening\n")
    assert misquoted(guide, widened) == ["core-is-mission-agnostic: sentinel.screening"]
    assert misquoted(guide.replace("| `passes-offline` |", "| `passes-no-network` |"), importlinter) == [
        "passes-offline: no row"
    ]


# ----------------------------------------------------------------- paths
def missing(markdown: str, doc: str) -> list[str]:
    return missing_paths(parse_markdown(markdown), (ROOT / doc).parent, ROOT)


@pytest.mark.parametrize("doc", DOCS)
def test_every_path_the_docs_name_exists(doc):
    text = read(doc)
    assert missing(text, doc) == []

    stale = text + "\n`sentinel/sync/jetstream.py` and [the old guide](old-guide.md)\n"
    assert missing(stale, doc) == ["sentinel/sync/jetstream.py", "old-guide.md"]


# ----------------------------------------------------------------- index
def markdown_documents() -> list[str]:
    """Tracked and new (not ignored) Markdown files in the repository."""
    done = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return sorted(line for line in done.stdout.splitlines() if (ROOT / line).exists())


def unlisted(index: str, documents: list[str]) -> list[str]:
    """Documents whose repository path does not appear in the index as a whole token."""
    return [doc for doc in documents if not re.search(rf"(?<![\w/.-]){re.escape(doc)}(?![\w/.-])", index)]


def test_the_index_lists_every_markdown_document():
    documents = markdown_documents()
    assert {GUIDE, INDEX, "CONTRIBUTING.md", "README.md"} <= set(documents)
    index = read(INDEX)
    assert unlisted(index, documents) == []

    stale = index.replace("docs/risk-engine-design.md", "docs/risk-engine.md")
    assert unlisted(stale, documents) == ["docs/risk-engine-design.md"]
