"""Read the subset of SysML v2 textual notation that the trace needs.

This is not a SysML parser; `make sysml-check` runs the full grammar. This
reader lexes the notation (names, strings, comments, notes, symbols), groups
it into statements and `{ }` blocks, and interprets four constructs:

    requirement <'REQ-AREA-NNN'> name { doc /* text */ ... }
    satisfy [requirement] <requirement> by <part path>;
    verification <'VC-...'> name {
        objective { verify [requirement] <requirement>; }
        @Evidence { kind = EvidenceKind::<kind>; locator = "<where>"; }
        @Planned { milestone = "<M>"; reason = "<why>"; }
    }

Everything else is structure it walks past. A model it cannot read
faithfully raises ModelError naming the file and line, rather than tracing
part of it.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from collections.abc import Iterable, Mapping


class ModelError(ValueError):
    """The model cannot be read faithfully; the message names file and line."""


@dataclasses.dataclass(frozen=True)
class Requirement:
    id: str
    name: str
    text: str


@dataclasses.dataclass(frozen=True)
class Satisfy:
    requirement: str   # the requirement's name or id as referenced
    by: str            # the satisfying part's path, as written


@dataclasses.dataclass(frozen=True)
class Evidence:
    kind: str
    locator: str


@dataclasses.dataclass(frozen=True)
class VerificationCase:
    id: str
    name: str
    verifies: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    planned: str | None   # the milestone, when the evidence is not built yet
    reason: str = ""      # why it is not built yet


@dataclasses.dataclass(frozen=True)
class Model:
    requirements: tuple[Requirement, ...]
    satisfactions: tuple[Satisfy, ...]
    verifications: tuple[VerificationCase, ...]
    parts: frozenset[str] = frozenset()   # every declared part usage name


# ------------------------------------------------------------------ lexing
_TOKEN = re.compile(
    r"""
      (?P<space>\s+)
    | (?P<blocknote>//\*.*?\*/)
    | (?P<note>//[^\n]*)
    | (?P<comment>/\*.*?\*/)
    | (?P<string>"(?:[^"\\\n]|\\.)*")
    | (?P<unterminated>/\*|")
    | (?P<name>'(?:[^'\\\n]|\\.)*'|[A-Za-z_][A-Za-z0-9_]*)
    | (?P<number>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)
    | (?P<symbol>::>|::|:>>|:>|\.\.|==|!=|<=|>=|->|[{}();:<>=@\#,.\[\]~*+\-/!|&^%?$])
    """,
    re.S | re.X,
)
_SKIPPED = {"space", "blocknote", "note"}


@dataclasses.dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    line: int


def _lex(text: str, source: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos, line = 0, 1
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None:
            raise ModelError(f"{source}:{line}: unexpected character {text[pos]!r}")
        kind = match.lastgroup or ""
        if kind == "unterminated":
            raise ModelError(f"{source}:{line}: unterminated comment or string")
        if kind not in _SKIPPED:
            tokens.append(_Token(kind, match.group(), line))
        line += match.group().count("\n")
        pos = match.end()
    return tokens


# --------------------------------------------------------------- grouping
@dataclasses.dataclass(frozen=True)
class _Statement:
    head: tuple[_Token, ...]              # tokens up to ';', '{' or a comment
    line: int
    doc: str | None = None                # text of a comment that ends the statement
    body: tuple[_Statement, ...] | None = None


def _doc_text(comment: str) -> str:
    lines = (re.sub(r"^\s*\*?", "", line) for line in comment[2:-2].splitlines())
    return " ".join(" ".join(lines).split())


def _is_symbol(token: _Token, text: str) -> bool:
    return token.kind == "symbol" and token.text == text


def _group(tokens: list[_Token], source: str) -> tuple[_Statement, ...]:
    """Statements end at ';', at a comment (`doc /* */`) or at a block."""
    levels: list[list[_Statement]] = [[]]
    opened: list[tuple[list[_Token], int]] = []
    head: list[_Token] = []

    def flush(doc: str | None = None, line: int = 0) -> None:
        if head or doc is not None:
            levels[-1].append(_Statement(tuple(head), head[0].line if head else line, doc))
        head.clear()

    for token in tokens:
        if token.kind == "comment":
            flush(_doc_text(token.text), token.line)
        elif _is_symbol(token, ";"):
            flush()
        elif _is_symbol(token, "{"):
            opened.append((list(head), token.line))
            levels.append([])
            head.clear()
        elif _is_symbol(token, "}"):
            if not opened:
                raise ModelError(f"{source}:{token.line}: unbalanced '}}'")
            flush()
            body = tuple(levels.pop())
            block_head, line = opened.pop()
            levels[-1].append(_Statement(tuple(block_head), block_head[0].line if block_head else line, None, body))
        else:
            head.append(token)
    if opened:
        raise ModelError(f"{source}:{opened[-1][1]}: unbalanced '{{' is never closed")
    flush()
    return tuple(levels[0])


# ---------------------------------------------------------- interpretation
_MODIFIERS = {"public", "private", "protected", "ref", "assert"}


def _words(statement: _Statement) -> tuple[_Token, ...]:
    head = statement.head
    while head and head[0].kind == "name" and head[0].text in _MODIFIERS:
        head = head[1:]
    return head


def _keyword(head: tuple[_Token, ...]) -> str | None:
    return head[0].text if head and head[0].kind == "name" else None


def _is_definition(head: tuple[_Token, ...]) -> bool:
    return len(head) > 1 and head[1].text == "def"


def _metadata_name(head: tuple[_Token, ...]) -> str | None:
    """`Evidence` for `@Evidence { ... }`, else None."""
    return head[1].text if len(head) >= 2 and _is_symbol(head[0], "@") else None


def _mentions_satisfy(head: tuple[_Token, ...]) -> bool:
    return any(t.kind == "name" and t.text == "satisfy" for t in head)


def _unquote(text: str) -> str:
    return text[1:-1] if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"" else text


def _last_name(tokens: Iterable[_Token]) -> str | None:
    names = [t.text for t in tokens if t.kind == "name"]
    return _unquote(names[-1]) if names else None


def _identity(head: tuple[_Token, ...], source: str) -> tuple[str | None, str | None]:
    """(short name, name) of `keyword <'short'> name ...`."""
    rest = head[1:]
    short = None
    if rest and _is_symbol(rest[0], "<"):
        if len(rest) < 3 or not _is_symbol(rest[2], ">"):
            raise ModelError(f"{source}:{head[0].line}: malformed short name")
        short, rest = _unquote(rest[1].text), rest[3:]
    name = _unquote(rest[0].text) if rest and rest[0].kind == "name" else None
    return short, name


def _requirement(statement: _Statement, head: tuple[_Token, ...], source: str) -> Requirement:
    where = f"{source}:{statement.line}"
    rid, name = _identity(head, source)
    if rid is None:
        raise ModelError(f"{where}: requirement {name!r} has no id (<'REQ-AREA-NNN'>)")
    if name is None:
        raise ModelError(f"{where}: requirement {rid} has no name")
    docs = [s.doc for s in statement.body or () if _keyword(_words(s)) == "doc" and s.doc]
    if not docs:
        raise ModelError(f"{where}: requirement {rid} has no doc text")
    return Requirement(rid, name, docs[0])


def _satisfy(head: tuple[_Token, ...], source: str) -> Satisfy:
    words = head[1:]
    if words and words[0].text == "requirement":
        words = words[1:]
    split = next((i for i, t in enumerate(words) if t.kind == "name" and t.text == "by"), None)
    target = _last_name(words[:split]) if split is not None else None
    part = "".join(t.text for t in words[split + 1:]) if split is not None else ""
    if target is None or not part:
        raise ModelError(f"{source}:{head[0].line}: satisfy needs a requirement and 'by <part>'")
    return Satisfy(target, part)


def _verify_target(statement: _Statement, source: str) -> str:
    target = _last_name(t for t in _words(statement)[1:] if t.text != "requirement")
    if target is None:
        raise ModelError(f"{source}:{statement.line}: verify needs a requirement")
    return target


def _fields(statement: _Statement, source: str) -> dict[str, str]:
    """`name = value;` members of a metadata body; a value is a string or a name."""
    fields = {}
    for member in statement.body or ():
        head = _words(member)
        if len(head) < 3 or not _is_symbol(head[1], "="):
            raise ModelError(f"{source}:{member.line}: expected 'feature = value;' in metadata")
        value = head[2].text if head[2].kind == "string" else _last_name(head[2:])
        fields[head[0].text] = _unquote(value or "")
    return fields


def _evidence(statement: _Statement, source: str) -> Evidence:
    fields = _fields(statement, source)
    for required in ("kind", "locator"):
        if not fields.get(required):
            raise ModelError(f"{source}:{statement.line}: @Evidence needs a {required}")
    return Evidence(fields["kind"], fields["locator"])


def _verification(statement: _Statement, head: tuple[_Token, ...], source: str) -> VerificationCase:
    where = f"{source}:{statement.line}"
    vid, name = _identity(head, source)
    if vid is None or name is None:
        raise ModelError(f"{where}: verification case needs an id (<'VC-...'>) and a name")
    verifies: list[str] = []
    evidence: list[Evidence] = []
    planned, reason = None, ""
    for member in statement.body or ():
        words = _words(member)
        if _keyword(words) == "objective":
            verifies += [_verify_target(s, source) for s in member.body or () if _keyword(_words(s)) == "verify"]
        elif _metadata_name(words) == "Evidence":
            evidence.append(_evidence(member, source))
        elif _metadata_name(words) == "Planned":
            fields = _fields(member, source)
            planned, reason = fields.get("milestone"), fields.get("reason", "")
            if not planned:
                raise ModelError(f"{source}:{member.line}: @Planned needs a milestone")
    return VerificationCase(vid, name, tuple(verifies), tuple(evidence), planned, reason)


@dataclasses.dataclass
class _Found:
    requirements: list[tuple[Requirement, str]] = dataclasses.field(default_factory=list)
    satisfactions: list[Satisfy] = dataclasses.field(default_factory=list)
    verifications: list[tuple[VerificationCase, str]] = dataclasses.field(default_factory=list)
    parts: set[str] = dataclasses.field(default_factory=set)


def _interpret(statements: Iterable[_Statement], source: str, found: _Found) -> None:
    for statement in statements:
        head = _words(statement)
        keyword = _keyword(head)
        where = f"{source}:{statement.line}"
        if keyword == "requirement" and not _is_definition(head):
            found.requirements.append((_requirement(statement, head, source), where))
        elif keyword == "satisfy":
            found.satisfactions.append(_satisfy(head, source))
        elif _mentions_satisfy(head):
            raise ModelError(f"{where}: this form of satisfy (e.g. negated) is not traced; write 'satisfy r by p;'")
        elif keyword == "verification" and not _is_definition(head):
            found.verifications.append((_verification(statement, head, source), where))
        elif keyword == "part" and not _is_definition(head):
            _, name = _identity(head, source)
            if name:
                found.parts.add(name)
        if statement.body:
            _interpret(statement.body, source, found)


def _reject_duplicates(kind: str, items: list[tuple[str, str]]) -> None:
    seen: set[str] = set()
    for key, where in items:
        if key in seen:
            raise ModelError(f"{where}: duplicate {kind} {key}")
        seen.add(key)


def read_model(sources: Mapping[str, str]) -> Model:
    """Read every source (name -> text) into one model."""
    found = _Found()
    for source, text in sources.items():
        _interpret(_group(_lex(text, source), source), source, found)
    _reject_duplicates("requirement id", [(r.id, w) for r, w in found.requirements])
    _reject_duplicates("requirement name", [(r.name, w) for r, w in found.requirements])
    _reject_duplicates("verification case id", [(v.id, w) for v, w in found.verifications])
    _reject_duplicates("verification case name", [(v.name, w) for v, w in found.verifications])
    return Model(
        tuple(r for r, _ in found.requirements),
        tuple(found.satisfactions),
        tuple(v for v, _ in found.verifications),
        frozenset(found.parts),
    )


def read_model_dir(directory: pathlib.Path) -> Model:
    """Read every *.sysml file in a directory, in name order."""
    paths = sorted(directory.glob("*.sysml"))
    return read_model({f"{directory.name}/{p.name}": p.read_text(encoding="utf-8") for p in paths})
