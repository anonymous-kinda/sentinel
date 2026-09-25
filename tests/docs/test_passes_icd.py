"""docs/icd/passes-api.md against the routes and the validation behind them.

PUT /api/passes/unit refuses a unit the node cannot compute for. The
bounds the document must state are formatted from the constants in
sentinel/passes/unit.py, so a bound that moves fails here until the
document moves with it.

Every status a route in sentinel/api/pass_routes.py can answer with is read
from the source (an HTTPException it raises, the status its decorator sets,
a query parameter FastAPI bounds), and the document's section for that
route must name it. The 503 is also shown to happen for the reason the
document gives.
"""

import ast
import datetime as dt
import json
import pathlib
import re

from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.settings import Settings
from sentinel.clock import FixedClock
from sentinel.passes.providers.skyfield_local import MAX_LEO_PERIOD_S
from sentinel.passes.unit import MAX_ALT_M, MAX_REACTION_TIME_MIN, MAX_UNIT_ID_CHARS, MIN_ALT_M

from .icd import ICD, ROOT, section, tree

PASSES_API = ICD / "passes-api.md"
PASS_ROUTES = "sentinel/api/pass_routes.py"
SNAPSHOT = ROOT / "fixtures" / "omm" / "celestrak-resource-20260924.json"
WV3 = 40115


def unit_bounds() -> list[str]:
    return [
        f"over {MAX_UNIT_ID_CHARS} characters",
        f"altitude outside [{MIN_ALT_M:g}, {MAX_ALT_M:g}] m",
        f"reaction time not positive or over {MAX_REACTION_TIME_MIN:g} min",
    ]


def unit_problems(doc: str) -> list[str]:
    unit = section(doc, "Unit")
    return [f"the unit bound {bound!r} is not stated" for bound in unit_bounds() if bound not in unit]


def test_the_unit_section_states_every_bound_the_code_enforces():
    assert unit_problems(PASSES_API.read_text()) == []


def test_a_stale_bound_is_caught():
    stale = PASSES_API.read_text().replace(f"{MAX_ALT_M:g}] m", "8849] m")
    assert unit_problems(stale) == [f"the unit bound 'altitude outside [{MIN_ALT_M:g}, {MAX_ALT_M:g}] m' is not stated"]


# ------------------------------------------------------------------ statuses
def _route(decorator: ast.expr) -> tuple[str, str] | None:
    """("GET", "/api/passes") for `@app.get("/api/passes", ...)`."""
    if (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
    ):
        return decorator.func.attr.upper(), decorator.args[0].value
    return None


def _statuses(function: ast.FunctionDef | ast.AsyncFunctionDef, decorator: ast.Call) -> set[int]:
    """What a route answers besides 200: the HTTPExceptions it raises, its
    decorator's status_code, and 422 for a query parameter FastAPI bounds."""
    raised = {
        node.args[0].value
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "HTTPException"
        and isinstance(node.args[0], ast.Constant)
    }
    declared = {k.value.value for k in decorator.keywords if k.arg == "status_code" and isinstance(k.value, ast.Constant)}
    bounded = any(
        isinstance(default, ast.Call)
        and isinstance(default.func, ast.Name)
        and default.func.id == "Query"
        and {k.arg for k in default.keywords} & {"ge", "gt", "le", "lt"}
        for default in function.args.defaults
    )
    return raised | declared | ({422} if bounded else set())


def route_statuses(module: ast.Module) -> dict[tuple[str, str], set[int]]:
    """(method, path) -> every status the route can answer besides 200."""
    routes = {}
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                route = _route(decorator)
                if route is not None and isinstance(decorator, ast.Call):
                    routes[route] = _statuses(node, decorator)
    return routes


def route_section(doc: str, method: str, path: str) -> str:
    """The level-2 section that shows `METHOD path`, followed by `?`, a backtick or a space."""
    mention = re.compile(rf"`{method} {re.escape(path)}[`?\s]")
    return next((chunk for chunk in re.split(r"^(?=## )", doc, flags=re.M) if mention.search(chunk)), "")


def undocumented_statuses(doc: str, routes: dict[tuple[str, str], set[int]]) -> list[str]:
    problems = []
    for (method, path), statuses in sorted(routes.items()):
        text = route_section(doc, method, path)
        if not text:
            problems.append(f"{method} {path}: no section shows it")
            continue
        problems += [f"{method} {path}: {status}" for status in sorted(statuses) if not re.search(rf"\b{status}\b", text)]
    return problems


def test_the_statuses_are_read_from_the_routes():
    routes = route_statuses(tree(PASS_ROUTES))
    assert routes[("GET", "/api/passes")] == {409, 422, 503}
    assert routes[("GET", "/api/passes/tracks")] == {404, 422}
    assert routes[("DELETE", "/api/passes/unit")] == {204}


def test_every_status_a_pass_route_answers_is_documented():
    assert undocumented_statuses(PASSES_API.read_text(), route_statuses(tree(PASS_ROUTES))) == []


def test_an_undocumented_status_or_route_is_caught():
    doc = PASSES_API.read_text()
    routes = route_statuses(tree(PASS_ROUTES))
    assert undocumented_statuses(doc.replace("`409`", "`410`"), routes) == ["GET /api/passes: 409"]
    assert undocumented_statuses(doc, {("GET", "/api/passes/history"): {404}}) == [
        "GET /api/passes/history: no section shows it"
    ]


# ------------------------------------------------------ the 503, and its cause
def element_set_bounds() -> list[str]:
    return ["mean motion is not positive", f"period is over {MAX_LEO_PERIOD_S / 60:g} minutes"]


def test_the_windows_section_states_when_an_element_set_cannot_be_used():
    windows = " ".join(section(PASSES_API.read_text(), "Windows and gaps").split())
    assert [bound for bound in element_set_bounds() if bound not in windows] == []


def test_an_imager_outside_low_earth_orbit_is_503_not_a_shorter_answer(tmp_path):
    """The document's cause of the 503, made to happen: WORLDVIEW-3 given a
    one-revolution-a-day element set. The node refuses the whole answer
    rather than leave the imager out, which would lengthen every gap."""
    records = json.loads(SNAPSHOT.read_text())
    for record in records:
        if int(record["NORAD_CAT_ID"]) == WV3:
            record["MEAN_MOTION"] = 1.0
    elements = pathlib.Path(tmp_path) / "elements.json"
    elements.write_text(json.dumps(records))
    settings = Settings(
        exercise=False, library=False, web_dist=None, var_dir=str(tmp_path / "var"), elements_path=str(elements)
    )
    clock = FixedClock(dt.datetime(2026, 9, 24, 6, 0, 30, tzinfo=dt.UTC))
    unit = {"unit_id": "EX-UNIT-1", "lat_deg": 35.26, "lon_deg": -116.68}
    with TestClient(create_app(settings, clock=clock, start_background=False)) as node:
        assert node.put("/api/passes/unit", json=unit).status_code == 200
        reply = node.get("/api/passes?hours=6")
    assert reply.status_code == 503
    assert reply.json()["detail"] == "an element set for a catalogued imager cannot be used"
