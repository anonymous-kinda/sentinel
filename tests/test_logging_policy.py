"""Policy: every log call in the product and its tooling uses a constant message.

Covers sentinel/, the release tooling (supplychain/, scripts/) and the
compliance generator (compliance/). Parses the source rather than trusting
review. A logging call whose first argument is an f-string, a %-format
string, a concatenation or a variable puts high-cardinality values into the
message and fails this test.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = (ROOT / "sentinel", ROOT / "supplychain", ROOT / "scripts", ROOT / "compliance")
LEVELS = {"debug", "info", "warning", "error", "exception", "critical"}
LOGGER_NAMES = {"log", "logger", "_log"}


def _is_log_call(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    target = node.func.value
    return node.func.attr in LEVELS and isinstance(target, ast.Name) and target.id in LOGGER_NAMES


def _has_constant_message(call: ast.Call) -> bool:
    first = call.args[0] if call.args else None
    constant = isinstance(first, ast.Constant) and isinstance(first.value, str)
    return constant and "%" not in first.value and len(call.args) == 1


def offending_calls(packages=PACKAGES) -> list[str]:
    found = []
    for package in packages:
        for path in package.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if _is_log_call(node) and not _has_constant_message(node):
                    found.append(f"{path.relative_to(package.parent)}:{node.lineno}")
    return found


def test_log_messages_are_constants_with_values_as_fields():
    assert offending_calls() == []


def test_the_policy_catches_an_interpolated_message(tmp_path):
    (tmp_path / "bad.py").write_text('log.info(f"Unit {unit_id} moved")\n')
    assert offending_calls((tmp_path,)) == [f"{tmp_path.name}/bad.py:1"]
