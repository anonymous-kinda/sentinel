"""Every refusal reason the engine can return is known everywhere it is shown.

`sentinel.risk.types.RefusalReason` is the source. The console types it
(web/src/api/types.ts), explains it (REFUSAL_TEXT in web/src/lib/format.ts),
and the system model names it (mbse/sentinel.sysml). A reason missing from
any of them reaches an operator as a bare code, or not at all.
"""

import pathlib
import re

import pytest

from sentinel.risk.types import RefusalReason

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENGINE = {reason.value for reason in RefusalReason}


def _block(path: str, start: str, end: str) -> str:
    text = (ROOT / path).read_text()
    match = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, re.DOTALL)
    assert match, f"{path} has no block starting {start!r}"
    return match[1]


def web_type_union() -> set[str]:
    return set(re.findall(r'"([A-Z_]+)"', _block("web/src/api/types.ts", "export type RefusalReason =", ";")))


def web_refusal_text() -> set[str]:
    return set(re.findall(r"^\s*([A-Z_]+):", _block("web/src/lib/format.ts", "REFUSAL_TEXT", "};"), re.MULTILINE))


def sysml_enum() -> set[str]:
    return set(re.findall(r"enum ([A-Z_]+);", _block("mbse/sentinel.sysml", "enum def RefusalReason {", "}")))


@pytest.mark.parametrize("mirror", [web_type_union, web_refusal_text, sysml_enum], ids=lambda f: f.__name__)
def test_every_mirror_names_exactly_the_engines_refusal_reasons(mirror):
    assert mirror() == ENGINE
