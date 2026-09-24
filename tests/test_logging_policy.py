"""Policy: every log call in sentinel/ (and the release tooling) uses a constant message.

Parses the source rather than trusting review. A logging call whose first
argument is an f-string, a %-format string, a concatenation or a variable
puts high-cardinality values into the message and fails this test.
"""

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "sentinel"
LEVELS = {"debug", "info", "warning", "error", "exception", "critical"}
LOGGER_NAMES = {"log", "logger", "_log"}


def offending_calls(src: pathlib.Path = SRC) -> list[str]:
    found = []
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            target = node.func.value
            if node.func.attr not in LEVELS or not (isinstance(target, ast.Name) and target.id in LOGGER_NAMES):
                continue
            first = node.args[0] if node.args else None
            constant = isinstance(first, ast.Constant) and isinstance(first.value, str)
            if not constant or "%" in first.value or len(node.args) > 1:
                found.append(f"{path.relative_to(src.parent)}:{node.lineno}")
    return found


def test_log_messages_are_constants_with_values_as_fields():
    assert offending_calls() == []


def test_release_tooling_follows_the_same_policy():
    root = SRC.parent
    assert offending_calls(root / "supplychain") + offending_calls(root / "scripts") == []
