"""Re-checkable evidence behind a not_affected VEX statement.

"The vulnerable Go package is not linked" is checked against the shipped
binary's function-name table. An absence check that cannot see anything
must not pass, so a positive control (a package that IS linked) is required.
"""

import pytest

from supplychain.evidence import EvidenceError, GoPackageAbsent


def binary(tmp_path, *symbols: str):
    path = tmp_path / "nats-server"
    path.write_bytes(b"\x7fELF" + b"\x00".join(s.encode() for s in symbols) + b"\x00")
    return path


CHECK = GoPackageAbsent(package="golang.org/x/crypto/openpgp", control="golang.org/x/crypto/bcrypt")


def test_passes_when_the_package_is_absent_and_the_control_is_present(tmp_path):
    CHECK.verify(binary(tmp_path, "golang.org/x/crypto/bcrypt.GenerateFromPassword", "main.main"))


def test_fails_when_the_vulnerable_package_is_linked(tmp_path):
    path = binary(tmp_path, "golang.org/x/crypto/bcrypt.Cost", "golang.org/x/crypto/openpgp.ReadKeyRing")
    with pytest.raises(EvidenceError, match="openpgp"):
        CHECK.verify(path)


def test_fails_when_the_control_is_missing_because_absence_then_proves_nothing(tmp_path):
    with pytest.raises(EvidenceError, match="control"):
        CHECK.verify(binary(tmp_path, "main.main"))


def test_fails_when_the_binary_is_missing(tmp_path):
    with pytest.raises(EvidenceError, match="missing"):
        CHECK.verify(tmp_path / "nope")
