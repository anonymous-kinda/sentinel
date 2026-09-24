"""scripts/sysml_check.py: the model against the full SysML v2 grammar.

The real parser (the pilot implementation's grammar, ported to textX by
sysml2py) runs in an isolated environment (`make sysml-check`, CI job mbse),
because sysml2py pins astropy<6, which has no Python 3.13 wheels. These tests
pin the wrapper: how errors are reported, and that a validator which accepts
a known-bad model is not trusted to have checked anything.
"""

import logging

import pytest

from mbse.syntax import KNOWN_BAD, SysmlSyntaxError, ValidatorUntrustworthy, check, main


class FakeParser:
    """Rejects the known-bad control and any text containing 'BROKEN'."""

    def __init__(self, accept_everything=False):
        self.accept_everything = accept_everything
        self.parsed = []

    def parse(self, text):
        self.parsed.append(text)
        if self.accept_everything:
            return
        if text == KNOWN_BAD:
            raise SysmlSyntaxError(1, 30, "Expected ';'")
        for number, line in enumerate(text.splitlines(), start=1):
            if "BROKEN" in line:
                raise SysmlSyntaxError(number, line.index("BROKEN") + 1, "Expected something else")


@pytest.fixture
def files(tmp_path):
    good = tmp_path / "good.sysml"
    good.write_text("package Good { part def A; }\n")
    bad = tmp_path / "bad.sysml"
    bad.write_text("package Bad {\n    part def BROKEN\n}\n")
    return good, bad


def test_clean_files_have_no_problems(files):
    good, _ = files
    assert check([good], FakeParser()) == []


def test_a_syntax_error_is_reported_with_file_line_and_column(files):
    good, bad = files
    problems = check([good, bad], FakeParser())
    assert [(p.path, p.line, p.col) for p in problems] == [(str(bad), 2, 14)]
    assert "Expected" in problems[0].message


def test_a_validator_that_accepts_a_known_bad_model_is_not_trusted(files):
    good, _ = files
    parser = FakeParser(accept_everything=True)
    with pytest.raises(ValidatorUntrustworthy):
        check([good], parser)
    assert parser.parsed == [KNOWN_BAD]          # the control runs before any model file


def test_main_exit_codes_and_log_messages(files, caplog):
    good, bad = files
    with caplog.at_level(logging.INFO):
        assert main([str(good)], FakeParser) == 0
        assert main([str(good), str(bad)], FakeParser) == 1
        assert main([str(good)], lambda: FakeParser(accept_everything=True)) == 2
    messages = [r.getMessage() for r in caplog.records]
    assert "SysML syntax checked" in messages
    assert "SysML syntax error" in messages
    assert "SysML validator not trusted" in messages
    error = next(r for r in caplog.records if r.getMessage() == "SysML syntax error")
    assert error.fields["path"] == str(bad) and error.fields["line"] == 2


def test_main_without_the_validator_installed_fails_loudly(files, caplog):
    good, _ = files

    def not_installed():
        raise ModuleNotFoundError("No module named 'textx'")

    with caplog.at_level(logging.INFO):
        assert main([str(good)], not_installed) == 2
    assert any(r.getMessage() == "SysML validator not installed" for r in caplog.records)


def test_main_with_no_files_is_an_error_not_a_pass(caplog):
    with caplog.at_level(logging.INFO):
        assert main([], FakeParser) == 2
