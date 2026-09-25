"""Does an operator's question hold a position? (ADR-010)

With hosted AI on, the question's text goes to Jev and to Claude. A ground
unit's position never leaves its edge node, so a question that holds one is
routed and phrased on the node only (policy.py). Either rule is enough:

  * The unit this node holds. A decimal number in the question that states
    the unit's latitude or longitude, at the precision typed ("34.05" for
    34.0522). A whole number alone is not matched: it is an hour, a count
    or a catalog number far more often than a one-degree position.
  * Position notation, whoever the position belongs to: an MGRS grid
    reference, a number with a degree sign, a pair with hemisphere letters
    ("38.90N 77.04W"), or a pair of decimal degrees ("38.8977, -77.0365").

A false positive costs one local answer; a false negative sends a position
off the node, so the rules lean wide. Nothing here logs or returns the
text it matched.
"""

from __future__ import annotations

import re

from .grounding import numbers_in_text, states

Position = tuple[float, float]

# Zone (1-60), latitude band (C-X without I and O), 100 km square (two letters
# without I and O), then easting and northing: "11SLT8520012345", "11S LT 852 123".
_MGRS = re.compile(r"\b\d{1,2}\s?[C-HJ-NP-X]\s?[A-HJ-NP-Z]{2}\s?\d{1,5}(?:\s?\d{1,5})?\b", re.IGNORECASE)
_DEGREES = re.compile(r"\d\s*[°º]")
# Upper case only: "5 s" is five seconds, not the southern hemisphere.
_HEMISPHERES = re.compile(r"\d\s?[NS]\b[\s,]*\d{1,3}(?:\.\d+)?\s?[EW]\b")
# Three decimals (about 100 m) or more on both halves: pasted from a map.
_DECIMAL_PAIR = re.compile(r"(?<![\d.])[-+]?\d{1,3}\.\d{3,}\s*[,;\s]\s*[-+]?\d{1,3}\.\d{3,}(?![\d.])")
NOTATION = (_MGRS, _DEGREES, _HEMISPHERES, _DECIMAL_PAIR)


def holds_position(text: str, unit: Position | None) -> bool:
    return any(pattern.search(text) for pattern in NOTATION) or (unit is not None and _states_unit(text, unit))


def _states_unit(text: str, unit: Position) -> bool:
    """A sign is typed as '-', 'S' or 'W', so a coordinate matches by magnitude."""
    return any(
        "." in token and any(states(token, abs(coordinate)) for coordinate in unit) for token in numbers_in_text(text)
    )
