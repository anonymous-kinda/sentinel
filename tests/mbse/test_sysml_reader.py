"""The SysML v2 subset reader: what the trace generator takes from the model.

It reads requirement usages (id, name, doc text), satisfy relations and
verification cases (verify targets, @Evidence, @Planned). Anything else in
the notation is structure it walks past. A model it cannot read faithfully
raises ModelError with the file and line, rather than tracing half of it.
"""

import pytest

from mbse.sysml import Evidence, ModelError, read_model

REQUIREMENTS = """
package Reqs {
    doc /* Requirements. A URL in a doc, https://example.org/x, is text. */
    private import ScalarValues::*;

    // A note is not part of the model.
    requirement <'REQ-DDIL-001'> consoleWhileDenied {
        doc /* While the link is DENIED, the edge console answers
             * with p95 latency below 200 ms. */
        attribute consoleP95_ms : Real;
        require constraint { consoleP95_ms < 200.0 }
    }

    requirement <'REQ-RISK-001'> caraAgreement {
        doc /* Agrees with CARA. */
    }
}
"""

ARCHITECTURE = """
package Arch {
    private import Reqs::*;
    part def Node { part console; }
    part edge : Node;
    satisfy consoleWhileDenied by edge.console;
    satisfy requirement Reqs::caraAgreement by edge;
}
"""

VERIFICATION = """
package Verif {
    private import Reqs::*;
    verification <'VC-DDIL-001'> vcConsole {
        doc /* The DENIED scenario. */
        objective {
            verify consoleWhileDenied;
        }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/a.py::test_b"; }
    }
    verification <'VC-RISK-001'> vcCara {
        objective { verify requirement Reqs::caraAgreement; }
        @Planned { milestone = "M4"; reason = "not built yet"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/c.py::test_d"; }
    }
}
"""


def model(**overrides):
    sources = {"reqs.sysml": REQUIREMENTS, "arch.sysml": ARCHITECTURE, "verif.sysml": VERIFICATION}
    sources.update(overrides)
    return read_model(sources)


def test_requirements_carry_id_name_and_doc_text():
    reqs = {r.id: r for r in model().requirements}
    assert set(reqs) == {"REQ-DDIL-001", "REQ-RISK-001"}
    ddil = reqs["REQ-DDIL-001"]
    assert ddil.name == "consoleWhileDenied"
    # Doc text is whitespace-normalised, with the comment's leading stars gone.
    assert ddil.text == "While the link is DENIED, the edge console answers with p95 latency below 200 ms."


def test_satisfy_relations_name_the_requirement_and_the_part():
    pairs = {(s.requirement, s.by) for s in model().satisfactions}
    assert pairs == {("consoleWhileDenied", "edge.console"), ("caraAgreement", "edge")}


def test_part_usage_names_are_collected_so_satisfy_paths_can_be_checked():
    text = """
    package P {
        part def Node { part console; private part riskEngine : RiskEngine; ref part peer : Node; }
        part def Unused;
        part system { part edge : Node; }
    }
    """
    assert read_model({"p.sysml": text}).parts == frozenset({"console", "riskEngine", "peer", "system", "edge"})


def test_verification_cases_carry_targets_evidence_and_planned_marker():
    cases = {c.id: c for c in model().verifications}
    console = cases["VC-DDIL-001"]
    assert console.name == "vcConsole"
    assert console.verifies == ("consoleWhileDenied",)
    assert console.evidence == (Evidence("harness", "DENIED"), Evidence("pytest", "tests/a.py::test_b"))
    assert console.planned is None

    cara = cases["VC-RISK-001"]
    assert cara.verifies == ("caraAgreement",)
    assert cara.planned == "M4"
    assert cara.reason == "not built yet"


def test_notes_and_text_inside_comments_and_strings_are_not_structure():
    text = """
    package P {
        // requirement <'REQ-X-001'> commentedOut { doc /* no */ }
        requirement <'REQ-X-002'> real {
            doc /* Braces { and ; and // inside a doc are text. */
        }
        verification <'VC-X-002'> vc {
            objective { verify real; }
            @Evidence { kind = EvidenceKind::pytest; locator = "tests/x.py::t{;}"; }
        }
    }
    """
    m = read_model({"p.sysml": text})
    assert [r.id for r in m.requirements] == ["REQ-X-002"]
    assert m.requirements[0].text == "Braces { and ; and // inside a doc are text."
    assert m.verifications[0].evidence == (Evidence("pytest", "tests/x.py::t{;}"),)


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("package P { part p { }", "unbalanced"),
        ("package P { part p; } }", "unbalanced"),
        ("package P { doc /* never closed }", "unterminated"),
        ("package P { requirement noId { doc /* x */ } }", "id"),
        ("package P { requirement <'REQ-X-001'> noDoc; }", "doc"),
        ("package P { satisfy r; }", "satisfy"),
        ("package P { satisfy r by ; }", "satisfy"),
        ("package P { verification <'VC-1'> v { objective { verify ; } } }", "verify"),
        ('package P { verification <\'VC-1\'> v { @Evidence { kind = EvidenceKind::pytest; } } }', "locator"),
        ('package P { verification <\'VC-1\'> v { @Evidence { locator = "x"; } } }', "kind"),
    ],
)
def test_a_model_it_cannot_read_faithfully_raises_with_file_and_line(text, complaint):
    with pytest.raises(ModelError, match=complaint) as caught:
        read_model({"bad.sysml": text})
    assert "bad.sysml:1" in str(caught.value)


def test_duplicate_requirement_ids_and_names_are_rejected():
    twice = """
    package P {
        requirement <'REQ-X-001'> a { doc /* a */ }
        requirement <'REQ-X-001'> b { doc /* b */ }
    }
    """
    with pytest.raises(ModelError, match="REQ-X-001"):
        read_model({"p.sysml": twice})
    same_name = """
    package P {
        requirement <'REQ-X-001'> a { doc /* a */ }
        requirement <'REQ-X-002'> a { doc /* b */ }
    }
    """
    with pytest.raises(ModelError, match="duplicate"):
        read_model({"p.sysml": same_name})


def test_asserted_satisfy_is_read_and_a_negated_one_is_refused_not_dropped():
    asserted = "package P { part p; requirement <'REQ-X-001'> r { doc /* r */ } assert satisfy r by p; }"
    assert read_model({"p.sysml": asserted}).satisfactions[0].requirement == "r"
    negated = "package P { part p; requirement <'REQ-X-001'> r { doc /* r */ } assert not satisfy r by p; }"
    with pytest.raises(ModelError, match="satisfy"):
        read_model({"p.sysml": negated})


def test_definitions_are_not_usages():
    text = """
    package P {
        requirement def Shape { doc /* A requirement definition, not a traced usage. */ }
        verification def Campaign { objective { verify something; } }
    }
    """
    m = read_model({"p.sysml": text})
    assert m.requirements == ()
    assert m.verifications == ()
