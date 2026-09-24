"""OpenVEX assembly from reviewed statements, refusing anything a scan did not produce.

Rules (RA-5): a statement must answer a finding that a real scan reported;
a not_affected statement needs a justification and a written reason; the
document must satisfy the OpenVEX 0.2.0 schema, which requires at least one
statement - so with nothing to say, no document is written at all.
"""

import json

import pytest

from supplychain import vex
from supplychain.evidence import GoPackageAbsent
from supplychain.trivy import Finding

HEADER = """
[document]
id = "urn:sentinel:openvex:test"
author = "Sentinel maintainers"
role = "Document Creator"
version = 1
timestamp = "2026-09-23T00:00:00Z"
"""

STATEMENT = """
[[statement]]
vulnerability = "GO-2026-5932"
products = ["pkg:golang/github.com/nats-io/nats-server/v2@v2.15.0"]
subcomponents = ["pkg:golang/golang.org/x/crypto@v0.57.0"]
status = "not_affected"
justification = "vulnerable_code_not_present"
impact_statement = "x/crypto/openpgp is not linked into the shipped binary."
timestamp = "2026-09-23T00:00:00Z"
"""

EVIDENCE = """
[statement.evidence]
kind = "go-package-absent"
package = "golang.org/x/crypto/openpgp"
control = "golang.org/x/crypto/bcrypt"
binaries = ["x86_64/nats-server"]
"""

FINDING = Finding("GO-2026-5932", "pkg:golang/golang.org/x/crypto@v0.57.0", "x86_64/nats-server", "UNKNOWN")


def test_statements_load_with_their_evidence():
    meta, statements = vex.load(HEADER + STATEMENT + EVIDENCE)
    assert meta.author == "Sentinel maintainers"
    (s,) = statements
    assert s.vulnerability == "GO-2026-5932" and s.status == "not_affected"
    assert s.evidence == GoPackageAbsent("golang.org/x/crypto/openpgp", "golang.org/x/crypto/bcrypt")
    assert s.evidence_binaries == ("x86_64/nats-server",)


def test_not_affected_without_a_justification_is_refused():
    text = HEADER + STATEMENT.replace('justification = "vulnerable_code_not_present"\n', "")
    with pytest.raises(vex.VexError, match="justification"):
        vex.load(text)


def test_not_affected_without_a_written_reason_is_refused():
    text = HEADER + STATEMENT.replace('impact_statement = "x/crypto/openpgp is not linked into the shipped binary."\n', "")
    with pytest.raises(vex.VexError, match="impact_statement"):
        vex.load(text)


def test_a_justification_outside_the_openvex_vocabulary_is_refused():
    text = HEADER + STATEMENT.replace("vulnerable_code_not_present", "we_think_it_is_fine")
    with pytest.raises(vex.VexError, match="justification"):
        vex.load(text)


def test_an_unknown_status_is_refused():
    with pytest.raises(vex.VexError, match="status"):
        vex.load(HEADER + STATEMENT.replace('"not_affected"', '"ignored"'))


def test_affected_requires_an_action_statement():
    text = HEADER + STATEMENT.replace('"not_affected"', '"affected"')
    with pytest.raises(vex.VexError, match="action_statement"):
        vex.load(text)


def test_a_misspelled_key_is_refused_rather_than_ignored():
    with pytest.raises(vex.VexError, match="justifcation"):
        vex.load(HEADER + STATEMENT + 'justifcation = "typo"\n')


def test_a_statement_for_a_finding_no_scan_produced_is_stale():
    _, statements = vex.load(HEADER + STATEMENT)
    assert vex.stale(statements, [FINDING]) == []
    other = Finding("GO-2026-5932", "pkg:golang/golang.org/x/crypto@v0.58.0", "x86_64/nats-server", "UNKNOWN")
    assert vex.stale(statements, [other]) == statements
    assert vex.stale(statements, []) == statements


def test_the_document_is_openvex_with_products_and_subcomponents():
    meta, statements = vex.load(HEADER + STATEMENT)
    doc = vex.document(meta, statements)
    assert doc["@context"] == "https://openvex.dev/ns/v0.2.0"
    assert doc["@id"] == "urn:sentinel:openvex:test" and doc["version"] == 1
    (st,) = doc["statements"]
    assert st["vulnerability"] == {"name": "GO-2026-5932"}
    assert st["products"] == [
        {
            "@id": "pkg:golang/github.com/nats-io/nats-server/v2@v2.15.0",
            "subcomponents": [{"@id": "pkg:golang/golang.org/x/crypto@v0.57.0"}],
        }
    ]
    assert st["justification"] == "vulnerable_code_not_present"
    assert "evidence" not in st  # evidence is our check, not an OpenVEX field
    vex.validate_document(doc)


def test_an_empty_document_is_refused_because_the_schema_requires_a_statement():
    meta, _ = vex.load(HEADER)
    with pytest.raises(vex.VexError, match="at least one statement"):
        vex.document(meta, [])


def write_scan(path, found):
    results = [
        {
            "Target": f.target,
            "Vulnerabilities": [
                {"VulnerabilityID": f.vulnerability, "PkgIdentifier": {"PURL": f.purl}, "Severity": f.severity}
            ],
        }
        for f in found
    ]
    path.write_text(json.dumps({"SchemaVersion": 2, "Results": results}))
    return path


def nats_binary(tools):
    (tools / "x86_64").mkdir(parents=True)
    (tools / "x86_64" / "nats-server").write_bytes(b"golang.org/x/crypto/bcrypt.Cost\x00main.main")


def test_build_writes_the_document_and_check_detects_drift(tmp_path):
    statements = tmp_path / "statements.toml"
    statements.write_text(HEADER + STATEMENT + EVIDENCE)
    scan = write_scan(tmp_path / "scan.json", [FINDING])
    nats_binary(tmp_path / "tools")
    out = tmp_path / "sentinel.openvex.json"
    args = dict(statements=statements, scans=[scan], tools_dir=tmp_path / "tools", out=out)
    vex.build(**args)
    assert json.loads(out.read_text())["statements"][0]["vulnerability"]["name"] == "GO-2026-5932"
    vex.build(**args, check=True)  # up to date
    out.write_text(out.read_text().replace("GO-2026-5932", "GO-0000-0000"))
    with pytest.raises(vex.VexError, match="out of date"):
        vex.build(**args, check=True)


def test_build_refuses_stale_statements(tmp_path):
    statements = tmp_path / "statements.toml"
    statements.write_text(HEADER + STATEMENT)
    scan = write_scan(tmp_path / "scan.json", [])
    with pytest.raises(vex.VexError, match="GO-2026-5932"):
        vex.build(statements=statements, scans=[scan], tools_dir=tmp_path, out=tmp_path / "o.json")


def test_build_refuses_when_the_evidence_no_longer_holds(tmp_path):
    statements = tmp_path / "statements.toml"
    statements.write_text(HEADER + STATEMENT + EVIDENCE)
    scan = write_scan(tmp_path / "scan.json", [FINDING])
    (tmp_path / "tools" / "x86_64").mkdir(parents=True)
    (tmp_path / "tools" / "x86_64" / "nats-server").write_bytes(
        b"golang.org/x/crypto/bcrypt.Cost\x00golang.org/x/crypto/openpgp.ReadKeyRing"
    )
    with pytest.raises(vex.VexError, match="evidence"):
        vex.build(statements=statements, scans=[scan], tools_dir=tmp_path / "tools", out=tmp_path / "o.json")


def test_with_no_statements_no_document_exists(tmp_path):
    statements = tmp_path / "statements.toml"
    statements.write_text(HEADER)
    out = tmp_path / "sentinel.openvex.json"
    out.write_text("{}")  # left over from when there was a finding
    assert vex.build(statements=statements, scans=[], tools_dir=tmp_path, out=out) is None
    assert not out.exists()
