"""Number grounding: an AI-written answer may only state numbers it was given.

Every numeric token in the answer must match - at the precision the answer
states it - a number in the tool results (values, numbers inside returned
identifiers and names, or the length of a returned list), or a number in
the operator's own question. An answer that introduces any other number
is withheld and the raw tool results are shown instead.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Iterable
from typing import Any

_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
# Bounded by digits, not words: "10.9h" and "240700Z" are numbers too, and a
# unit glued to a figure must not hide it from the guard.
_NUMBER = re.compile(
    r"(?<![\d.,])"
    r"(?P<mant>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<exp>[eE][-+]?\d+|\s?[×x]\s?10(?:\^[-+−]?\d+|[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+))?"
    r"(?![\d])"
)


_DIGITS = re.compile(r"\d+")


@dataclasses.dataclass(frozen=True)
class GroundingResult:
    ok: bool
    unsupported: list[str]


def numbers_in_text(text: str) -> list[str]:
    return [m.group(0) for m in _NUMBER.finditer(text)]


def _unread_digits(text: str) -> list[str]:
    """Digits no number token covers: ".9", or the "9" of "0,9". The number
    pattern does not read them, so they would otherwise go unchecked. The
    one exception is a dotted continuation of a number ("1.13.0", "3.1.3"):
    a version, whose leading part is itself checked."""
    spans = [m.span() for m in _NUMBER.finditer(text)]
    return [
        m.group(0)
        for m in _DIGITS.finditer(text)
        if not any(a <= m.start() and m.end() <= b for a, b in spans) and not _dotted_continuation(text, m.start())
    ]


def _dotted_continuation(text: str, start: int) -> bool:
    return start >= 2 and text[start - 1] == "." and text[start - 2].isdigit()


def states(token: str, value: float) -> bool:
    """Does the number `token` state `value`, at the precision it is written?"""
    stated, sig = _parse(token)
    return math.isfinite(stated) and _same_at(stated, value, sig)


def _same_at(stated: float, value: float, sig: int) -> bool:
    return math.isclose(_round_sig(value, sig), _round_sig(stated, sig), rel_tol=1e-9, abs_tol=0.0)


def _parse(token: str) -> tuple[float, int]:
    """(value, significant digits stated)."""
    m = _NUMBER.fullmatch(token)
    mant = m.group("mant").replace(",", "")
    digits = mant.replace(".", "").lstrip("0") or "0"
    sig = max(len(digits), 1)
    exponent = 0
    if m.group("exp"):
        exp = m.group("exp").strip()
        if exp[0] in "eE":
            exponent = int(exp[1:])
        else:
            tail = exp.lstrip("×x ").removeprefix("10")
            exponent = int(tail.lstrip("^").replace("−", "-").translate(_SUP))
    try:
        return float(mant) * 10.0**exponent, sig
    except OverflowError:
        return math.inf, sig


def _round_sig(value: float, sig: int) -> float:
    if value == 0:
        return 0.0
    return round(value, sig - 1 - math.floor(math.log10(abs(value))))


def _evidence_numbers(evidence: Any) -> Iterable[float]:
    if isinstance(evidence, bool) or evidence is None:
        return
    if isinstance(evidence, (int, float)):
        if math.isfinite(evidence):
            # Magnitude: a sign is stated in words ("passed 3.2 h ago").
            yield abs(float(evidence))
    elif isinstance(evidence, str):
        for token in numbers_in_text(evidence):
            if math.isfinite(value := _parse(token)[0]):
                yield value
    elif isinstance(evidence, dict):
        for value in evidence.values():
            yield from _evidence_numbers(value)
    elif isinstance(evidence, (list, tuple)):
        yield float(len(evidence))
        for value in evidence:
            yield from _evidence_numbers(value)


def check_grounding(text: str, evidence: Any, question: str = "") -> GroundingResult:
    pool = list(_evidence_numbers(evidence)) + list(_evidence_numbers(question))
    unsupported = _unread_digits(text)
    for token in numbers_in_text(text):
        stated, sig = _parse(token)
        if not math.isfinite(stated):
            unsupported.append(token)
            continue
        if not any(_same_at(stated, v, sig) for v in pool):
            unsupported.append(token)
    return GroundingResult(not unsupported, unsupported)
