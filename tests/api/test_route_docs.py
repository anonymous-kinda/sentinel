"""A route's docstring is its OpenAPI description, and it names every status
the route raises.

An integrator learns what a route can answer from its description. A status
the code raises that the description leaves out is an interface nobody was
told about. Routes without a docstring are documented elsewhere (the pass
module, in docs/icd/passes-api.md) and are held to that document there.
"""

import ast
import pathlib
import re

API = pathlib.Path(__file__).resolve().parents[2] / "sentinel" / "api"
ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}


def _is_route(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ROUTE_METHODS
        for d in fn.decorator_list
    )


def _raised_statuses(fn: ast.AST) -> set[int]:
    return {
        node.args[0].value
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "HTTPException"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, int)
    }


def undocumented_statuses(source: str) -> list[str]:
    problems = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) or not _is_route(fn):
            continue
        doc = ast.get_docstring(fn)
        if doc is None:
            continue
        problems += [f"{fn.name}: {s}" for s in sorted(_raised_statuses(fn)) if not re.search(rf"\b{s}\b", doc)]
    return problems


def test_every_documented_route_names_the_statuses_it_raises():
    problems = [f"{p.name} {problem}" for p in sorted(API.glob("*.py")) for problem in undocumented_statuses(p.read_text())]
    assert problems == []


def test_the_check_catches_a_status_the_docstring_leaves_out():
    source = '''
@app.get("/x")
def x():
    """404 when the thing is unknown."""
    raise HTTPException(422, "cannot draw it")
'''
    assert undocumented_statuses(source) == ["x: 422"]
