"""What the ICD drift tests share: reading a document's tables and the
AsyncAPI document's channels, and reading facts out of the source by AST,
so neither side is restated by hand."""

from __future__ import annotations

import ast
import dataclasses
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
ICD = ROOT / "docs" / "icd"
ASYNCAPI = ICD / "asyncapi.yaml"
NODE_PREFIX = "node.{node_id}."

_HEADING = re.compile(r"^(#+)\s+(.*?)\s*$")
_BACKTICKED = re.compile(r"`([^`]+)`")


# ------------------------------------------------------------------ documents
def section(markdown: str, heading: str) -> str:
    """The text under `heading`, up to the next heading of the same or a higher level."""
    lines = markdown.splitlines()
    for start, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match[2] == heading:
            level = len(match[1])
            body = []
            for following in lines[start + 1 :]:
                nested = _HEADING.match(following)
                if nested and len(nested[1]) <= level:
                    break
                body.append(following)
            return "\n".join(body)
    raise AssertionError(f"no heading {heading!r}")


def table_rows(markdown: str, heading: str) -> list[list[str]]:
    """Body rows of the first table under `heading`, as stripped cells."""
    rows = []
    for line in section(markdown, heading).splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows[1:]  # drop the header row


def backticked(text: str) -> list[str]:
    return _BACKTICKED.findall(text)


def column(markdown: str, heading: str, index: int = 0) -> set[str]:
    """Every backticked token in one column of the table under `heading`."""
    return {token for row in table_rows(markdown, heading) for token in backticked(row[index])}


def compare(documented: set, actual: set, what: str) -> list[str]:
    """Both directions: in the code but undocumented, and documented but gone."""
    problems = [f"{what} {item} is not documented" for item in sorted(actual - documented, key=str)]
    problems += [f"{what} {item} is documented but not in the code" for item in sorted(documented - actual, key=str)]
    return problems


def nats_list(conf: str, key: str) -> set[str]:
    """A quoted-string list setting from a nats-server config, e.g. deny_exports."""
    match = re.search(rf"{key}:\s*\[([^\]]*)\]", conf)
    return set(re.findall(r'"([^"]+)"', match.group(1))) if match else set()


def load_asyncapi(text: str | None = None) -> dict:
    return yaml.safe_load(ASYNCAPI.read_text() if text is None else text)


def family(address: str) -> str:
    """The address without trailing parameter tokens: cdm.accepted.{event_id} -> cdm.accepted."""
    tokens = address.split(".")
    while tokens and tokens[-1].startswith("{"):
        tokens.pop()
    return ".".join(tokens)


def addresses(doc: dict) -> dict[str, str]:
    return {name: ch["address"] for name, ch in doc["channels"].items() if ch.get("address")}


def documented_node_kinds(doc: dict) -> set[str]:
    """The node-local event kinds an AsyncAPI document gives a channel: node.{node_id}.<kind>."""
    return {family(a)[len(NODE_PREFIX) :] for a in addresses(doc).values() if a.startswith(NODE_PREFIX)}


def drop_row(markdown: str, token: str) -> str:
    """The document with the table row naming `token` removed: a stale copy."""
    kept = [line for line in markdown.splitlines() if not (line.startswith("|") and f"`{token}`" in line)]
    assert len(kept) < len(markdown.splitlines()), f"no row names {token}"
    return "\n".join(kept) + "\n"


# --------------------------------------------------------------------- source
@dataclasses.dataclass(frozen=True)
class Source:
    path: str               # relative to the scanned root, for reporting
    module: ast.Module
    root: pathlib.Path = ROOT


def tree(relative: str) -> ast.Module:
    path = ROOT / relative
    return ast.parse(path.read_text(), filename=str(path))


def _source(path: pathlib.Path, root: pathlib.Path) -> Source:
    return Source(path.relative_to(root).as_posix(), ast.parse(path.read_text(), filename=str(path)), root)


def sources(*patterns: str, root: pathlib.Path = ROOT) -> list[Source]:
    return [_source(path, root) for pattern in patterns or ("**/*.py",) for path in sorted(root.glob(pattern))]


def trees(*patterns: str) -> list[ast.Module]:
    return [source.module for source in sources(*patterns)]


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def call_arguments(modules: list[ast.Module], callee: str, position: int) -> set[str]:
    """String constants passed at `position` to every call of `callee`."""
    found = set()
    for module in modules:
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and _callee(node) == callee and len(node.args) > position:
                arg = node.args[position]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def string_constants(modules: list[ast.Module], pattern: str) -> set[str]:
    """Every string constant that is, in full, a match for `pattern`."""
    regex = re.compile(pattern)
    return {
        node.value
        for module in modules
        for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and regex.fullmatch(node.value)
    }


def function(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"no function {name}")


def _text(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def keys_read(modules: list[ast.Module], variable: str) -> set[str]:
    """Constant keys read from a variable: `variable["k"]` and `variable.get("k")`."""
    found = set()
    for module in modules:
        for node in ast.walk(module):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == variable:
                found.add(_text(node.slice))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == variable
                and node.args
            ):
                found.add(_text(node.args[0]))
    return found - {None}


def headers_read(modules: list[ast.Module]) -> set[str]:
    """Constant names passed to `<anything>.headers.get(...)`."""
    return {
        _text(node.args[0])
        for module in modules
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "headers"
        and node.args
    } - {None}


def dict_keys(func: ast.AST) -> set[str]:
    """Constant keys of every dict literal inside a function."""
    return {_text(key) for node in ast.walk(func) if isinstance(node, ast.Dict) for key in node.keys} - {None}


def dict_values_for(modules: list[ast.Module], key: str) -> set[str]:
    """Constant values given to `key` in any dict literal."""
    return {
        _text(value)
        for module in modules
        for node in ast.walk(module)
        if isinstance(node, ast.Dict)
        for k, value in zip(node.keys, node.values)
        if _text(k) == key
    } - {None}


def returned_constants(func: ast.AST) -> set[str]:
    """String constants a function can return, including either arm of `a if c else b`."""
    found = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            arms = [node.value.body, node.value.orelse] if isinstance(node.value, ast.IfExp) else [node.value]
            found |= {_text(arm) for arm in arms}
    return found - {None}


def assigned_constants(modules: list[ast.Module], attribute: str) -> set[str]:
    """String constants assigned to `<x>.attribute`, or given as a field default."""
    found = set()
    for module in modules:
        for node in ast.walk(module):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == attribute:
                        found.add(_text(node.value))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == attribute:
                found.add(_text(node.value))
    return found - {None}


# ------------------------------------------------- what a module publishes
# A literal node-local subject: node.<node id>.<kind>, the kind in lower case.
_NODE_SUBJECT = re.compile(r"node\.[A-Za-z0-9_-]+\.([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)")
_MAX_HOPS = 3


@dataclasses.dataclass(frozen=True)
class Found:
    """String values found in the source, and where one could not be read."""

    values: set[str]
    unresolved: list[str]


class _Values:
    """The string constants an expression can take, within one module.

    Follows a literal, the leading literal of an f-string up to its first
    field, a module-level constant, a constant imported by name from another
    module in the scanned tree, and a function parameter back to the
    arguments of that function's calls in the same module. Anything else is
    unreadable, and the caller reports it rather than guessing.
    """

    def __init__(self, source: Source):
        self.source = source
        self.module = source.module
        self.constants = {
            target.id: node.value.value
            for node in source.module.body
            if isinstance(node, ast.Assign) and _text(node.value) is not None
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        self.imports = {
            alias.asname or alias.name: (node, alias.name)
            for node in source.module.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.parents = {child: parent for parent in ast.walk(source.module) for child in ast.iter_child_nodes(parent)}

    def of(self, expr: ast.AST, hops: int = 0) -> set[str] | None:
        if _text(expr) is not None:
            return {expr.value}
        if isinstance(expr, ast.JoinedStr):
            head = _text(expr.values[0]) if expr.values else None
            return {head.rstrip(".")} if head and head.endswith(".") else None
        if isinstance(expr, ast.Name):
            if expr.id in self.constants:
                return {self.constants[expr.id]}
            if expr.id in self.imports:
                return self._imported(expr.id, hops)
            return self._parameter(expr, hops)
        return None

    def _imported(self, alias: str, hops: int) -> set[str] | None:
        statement, name = self.imports[alias]
        origin = _imported_module(self.source, statement)
        if origin is None or hops >= _MAX_HOPS:
            return None
        return _Values(origin).of(ast.Name(id=name), hops + 1)

    def _parameter(self, name: ast.Name, hops: int) -> set[str] | None:
        func = self._enclosing(name)
        params = [] if func is None else _parameters(func)
        if name.id not in params or hops >= _MAX_HOPS:
            return None
        found: set[str] = set()
        for call in self._calls(func.name):
            arg = _argument(call, params.index(name.id), name.id)
            values = None if arg is None else self.of(arg, hops + 1)
            if values is None:
                return None
            found |= values
        return found or None

    def _enclosing(self, node: ast.AST) -> ast.FunctionDef | None:
        while node in self.parents:
            node = self.parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    def _calls(self, name: str) -> list[ast.Call]:
        return [node for node in ast.walk(self.module) if isinstance(node, ast.Call) and _callee(node) == name]


def _imported_module(source: Source, statement: ast.ImportFrom) -> Source | None:
    """The file in the scanned tree that `from <module> import ...` reads, relative or absolute."""
    package = pathlib.PurePosixPath(source.path).parent.parts
    base = package[: max(len(package) - statement.level + 1, 0)] if statement.level else ()
    parts = [*base, *(statement.module.split(".") if statement.module else [])]
    if not parts:
        return None
    for candidate in (source.root.joinpath(*parts).with_suffix(".py"), source.root.joinpath(*parts, "__init__.py")):
        if candidate.is_file():
            return _source(candidate, source.root)
    return None


def _parameters(func: ast.FunctionDef) -> list[str]:
    names = [a.arg for a in [*func.args.posonlyargs, *func.args.args]]
    return names[1:] if names and names[0] in ("self", "cls") else names


def _argument(call: ast.Call, index: int, keyword: str) -> ast.AST | None:
    if index < len(call.args):
        return call.args[index]
    return next((k.value for k in call.keywords if k.arg == keyword), None)


def _is_local_subject(call: ast.Call) -> bool:
    """`subjects.local(...)`, or `local(...)` inside the subjects module itself."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr == "local" and isinstance(func.value, ast.Name) and func.value.id == "subjects"
    return isinstance(func, ast.Name) and func.id == "local"


def _collect(scanned: list[Source], expressions) -> Found:
    values: set[str] = set()
    unresolved: list[str] = []
    for source in scanned:
        resolver = _Values(source)
        for expr in expressions(source.module):
            found = resolver.of(expr)
            if found is None:
                unresolved.append(f"{source.path}:{expr.lineno}")
            else:
                values |= found
    return Found(values, unresolved)


def node_kinds(scanned: list[Source]) -> Found:
    """Every node-local kind the code can publish: the suffix given to each
    `subjects.local` call, and the kind of each literal node.<id>.<kind>."""

    def suffixes(module: ast.Module):
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and _is_local_subject(node) and len(node.args) > 1:
                yield node.args[1]

    found = _collect(scanned, suffixes)
    literals = {m[1] for s in scanned for c in string_constants([s.module], _NODE_SUBJECT.pattern)
                if (m := _NODE_SUBJECT.fullmatch(c))}
    return Found(found.values | literals, found.unresolved)


def sentinel_kinds(scanned: list[Source]) -> Found:
    """Every value the code gives a `Sentinel-Kind` header in a dict literal."""

    def values(module: ast.Module):
        for node in ast.walk(module):
            if isinstance(node, ast.Dict):
                yield from (v for k, v in zip(node.keys, node.values) if _text(k) == "Sentinel-Kind")

    return _collect(scanned, values)


# ---------------------------------------------------- what plugs into a seam
def _is_protocol(cls: ast.ClassDef) -> bool:
    return any((b.id if isinstance(b, ast.Name) else getattr(b, "attr", None)) == "Protocol" for b in cls.bases)


def classes_implementing(scanned: list[Source], methods: set[str]) -> list[ast.ClassDef]:
    """Every class that defines all of `methods`: structural, as a Protocol is
    satisfied, so an implementation is found without being registered. The
    protocol's own definition is not one."""
    found = []
    for source in scanned:
        for node in ast.walk(source.module):
            if isinstance(node, ast.ClassDef) and not _is_protocol(node):
                defined = {f.name for f in node.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
                if methods <= defined:
                    found.append(node)
    return found


def mapping_keys(scanned: list[Source], callee: str, position: int, keyword: str) -> Found:
    """The string keys of the mapping given to every `callee(...)` call, at
    `position` or as `keyword`. A mapping that is not a dict literal, or a
    key the resolver cannot read, is reported as unresolved."""

    def keys(module: ast.Module):
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and _callee(node) == callee:
                mapping = _argument(node, position, keyword)
                if isinstance(mapping, ast.Dict):
                    yield from (key if key is not None else value for key, value in zip(mapping.keys, mapping.values))
                elif mapping is not None:
                    yield mapping

    return _collect(scanned, keys)
