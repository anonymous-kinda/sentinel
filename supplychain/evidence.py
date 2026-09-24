"""Evidence checks that back a VEX statement, re-run on every scan.

A Go binary keeps its function names (pclntab) even when stripped, so a
package that is linked leaves `<import path>.<Func>` strings behind. If the
vulnerable package's path never appears while a sibling package's does,
the vulnerable code is not in the binary: `vulnerable_code_not_present`.
"""

from __future__ import annotations

import dataclasses
import pathlib


class EvidenceError(Exception):
    """The evidence behind a statement does not hold (or cannot be checked)."""


@dataclasses.dataclass(frozen=True)
class GoPackageAbsent:
    package: str
    control: str

    def verify(self, binary: pathlib.Path) -> None:
        if not binary.is_file():
            raise EvidenceError(f"binary missing: {binary}")
        data = binary.read_bytes()
        if self.control.encode() not in data:
            raise EvidenceError(
                f"control package {self.control} not found in {binary}: an absence check here proves nothing"
            )
        if self.package.encode() in data:
            raise EvidenceError(f"{self.package} is linked into {binary}")
