"""CCSDS 508.0-B-1 Conjunction Data Messages: the ADR-001 seam.

Everything upstream of this package is source-specific. Everything
downstream consumes a CdmMessage (or the Conjunction derived from one) and
does not know or care where it came from.
"""

from .admission import Admitted, admit, read_message
from .kvn import CdmParseError, emit, parse, parse_bytes
from .model import CdmMessage, CdmSection, Comment, KvnField
from .to_conjunction import Conversion, resolve_radii, to_conjunction
from .validate import CdmRejected, CdmWarning, validate

__all__ = [
    "Admitted",
    "CdmMessage",
    "CdmParseError",
    "CdmRejected",
    "CdmSection",
    "CdmWarning",
    "Comment",
    "Conversion",
    "KvnField",
    "admit",
    "emit",
    "parse",
    "parse_bytes",
    "read_message",
    "resolve_radii",
    "to_conjunction",
    "validate",
]
