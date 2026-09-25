"""`.env` is the one place an operator writes local keys and opt-ins.

The development commands that use hosted AI read it, so a key is written
once. A variable already set in the environment wins, and an empty value
sets nothing, so the file can never hide a key the operator exported.
Values are never logged.
"""

import logging
import pathlib

import pytest

from sentinel import localenv

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET = "sk-test-0123456789"


def write(tmp_path, text: str) -> pathlib.Path:
    path = tmp_path / ".env"
    path.write_text(text)
    return path


def test_a_filled_line_is_loaded_and_named(tmp_path):
    env: dict[str, str] = {}
    assert localenv.load(write(tmp_path, f"ANTHROPIC_API_KEY={SECRET}\n"), env) == ["ANTHROPIC_API_KEY"]
    assert env == {"ANTHROPIC_API_KEY": SECRET}


def test_a_variable_already_set_wins(tmp_path):
    env = {"ANTHROPIC_API_KEY": "exported"}
    assert localenv.load(write(tmp_path, f"ANTHROPIC_API_KEY={SECRET}\n"), env) == []
    assert env == {"ANTHROPIC_API_KEY": "exported"}


def test_an_empty_value_sets_nothing_and_clears_nothing(tmp_path):
    env = {"TYPESAFE_API_KEY": "exported"}
    assert localenv.load(write(tmp_path, "TYPESAFE_API_KEY=\nANTHROPIC_API_KEY=\n"), env) == []
    assert env == {"TYPESAFE_API_KEY": "exported"}


def test_an_empty_variable_in_the_environment_is_filled(tmp_path):
    env = {"ANTHROPIC_API_KEY": ""}
    assert localenv.load(write(tmp_path, f"ANTHROPIC_API_KEY={SECRET}\n"), env) == ["ANTHROPIC_API_KEY"]


@pytest.mark.parametrize("line", [
    f"export ANTHROPIC_API_KEY={SECRET}",
    f'ANTHROPIC_API_KEY="{SECRET}"',
    f"ANTHROPIC_API_KEY='{SECRET}'",
    f"  ANTHROPIC_API_KEY = {SECRET}  ",
])
def test_the_shell_forms_of_a_line_are_read(tmp_path, line):
    env: dict[str, str] = {}
    localenv.load(write(tmp_path, line + "\n"), env)
    assert env == {"ANTHROPIC_API_KEY": SECRET}


def test_comments_blank_lines_and_malformed_lines_are_skipped(tmp_path):
    env: dict[str, str] = {}
    text = "# a comment\n\nnot an assignment\n=no-name\nSENTINEL_AI_CLOUD=1\n"
    assert localenv.load(write(tmp_path, text), env) == ["SENTINEL_AI_CLOUD"]


def test_no_file_is_not_an_error(tmp_path):
    assert localenv.load(tmp_path / ".env", {}) == []


def test_the_names_are_logged_and_a_value_never_is(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    localenv.load(write(tmp_path, f"ANTHROPIC_API_KEY={SECRET}\n"), {})
    [record] = [r for r in caplog.records if r.getMessage() == "Local env file loaded"]
    assert record.fields["names"] == ["ANTHROPIC_API_KEY"]
    assert all(SECRET not in repr(r.__dict__) for r in caplog.records)


@pytest.mark.parametrize("entry_point", ["scripts/ai_live_check.py", "scripts/ai_eval.py", "harness/demo.py"])
def test_the_commands_that_use_hosted_ai_read_the_file(entry_point):
    assert "localenv.load(" in (ROOT / entry_point).read_text()
