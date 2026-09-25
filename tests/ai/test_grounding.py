"""The number-grounding guard (design principle 5).

An AI-written answer may state a number only if that number, at the
precision stated, comes from a tool result - or from the operator's own
question. Anything else is withheld: the model has no path to the math.
"""

from sentinel.ai.grounding import check_grounding, numbers_in_text

EVIDENCE = {
    "events": [
        {"event_id": "99001-99118-20260924T205723", "secondary": "EX-DEB 118 (EXERCISE)",
         "pc": 0.006271, "pc_max": 0.00688, "miss_distance_m": 200.3, "time_to_mcp_h": 10.9},
        {"event_id": "99001-99412-20260925T075723", "secondary": "EX-DEB 412 (EXERCISE)",
         "pc": 3.62e-5, "miss_distance_m": 800.0, "time_to_mcp_h": 21.9},
        {"event_id": "99001-99733-20260925T215723", "secondary": "EX-DEB 733 (EXERCISE)",
         "pc": 2.4e-5, "miss_distance_m": 850.0, "time_to_mcp_h": 35.9},
    ]
}


def test_extracts_plain_decimal_scientific_and_superscript_forms():
    assert numbers_in_text("Pc 6.3e-3, 6.3×10⁻³, 6.3x10^-3, miss 200 m, 10.9 h") == [
        "6.3e-3", "6.3×10⁻³", "6.3x10^-3", "200", "10.9",
    ]


def test_numbers_from_tool_results_are_grounded():
    text = "EX-DEB 118 is RED: Pc 6.3×10⁻³ (worst case 6.9×10⁻³), miss 200 m, 10.9 h to MCP."
    assert check_grounding(text, EVIDENCE).ok


def test_an_invented_number_is_caught():
    result = check_grounding("EX-DEB 412 has Pc 2.0×10⁻² and should be maneuvered.", EVIDENCE)
    assert not result.ok
    assert result.unsupported == ["2.0×10⁻²"]


def test_precision_must_match_what_the_evidence_supports():
    assert check_grounding("Pc about 6×10⁻³", EVIDENCE).ok            # 1 significant figure
    assert not check_grounding("Pc 6.4×10⁻³", EVIDENCE).ok             # evidence rounds to 6.3


def test_counts_of_listed_items_are_grounded():
    assert check_grounding("3 events need attention.", EVIDENCE).ok
    assert not check_grounding("5 events need attention.", EVIDENCE).ok


def test_numbers_the_operator_asked_about_are_allowed():
    assert not check_grounding("Nothing inside 48 hours.", EVIDENCE).ok
    assert check_grounding("Nothing inside 48 hours.", EVIDENCE, question="anything red in the next 48 hours?").ok


def test_numbers_glued_to_units_or_letters_are_still_checked():
    """A unit suffix must not hide a number from the guard."""
    assert numbers_in_text("MCP in 99.9h, DTG 240700Z, p95") == ["99.9", "240700", "95"]
    assert not check_grounding("MCP in 99.9h", EVIDENCE).ok
    assert check_grounding("MCP in 10.9h", EVIDENCE).ok


def test_a_sign_carried_in_words_is_grounded():
    """'passed 3.2 h ago' states a tool's -3.2 as a magnitude."""
    assert check_grounding("The commit point passed 3.2 h ago.", {"time_to_mcp_h": -3.2}).ok


# What draft_decision returns: the event's facts, and the CDM the draft is
# made against, named by two hashes and a message id.
DRAFT = {
    "event_id": "99001-99118-20260924T205723", "secondary": "EX-DEB 118 (EXERCISE)", "secondary_id": "99118",
    "pc": 0.006271, "miss_distance_m": 200.3, "time_to_mcp_h": 10.9, "draft": True, "decision": "MANEUVER",
    "against": {
        "cdm_sha256": "3f41c07e9a2b6d15e8f0a4c3b27d9e61f5a8c0b4d2e7f9a1c3b5d7e9f0a2c4e6",
        "inputs_hash": "b7e2a9f58d06c3e8a5f7b1d9c2e4a6f8b0d3e5a7c9f1b2d4e6a8c0e2f4a6b8d0",
        "message_id": "EX-RED-03-20260923T120500",
    },
}


def test_digits_inside_a_hash_or_an_id_never_ground_a_quantity():
    """'41' inside a sha256 is part of a name, not a miss distance. Neither
    are the date and time inside an event id or a message id."""
    assert check_grounding("Miss 200 m.", DRAFT).ok
    result = check_grounding("Miss 41 m.", DRAFT)
    assert not result.ok and result.unsupported == ["41"]
    assert not check_grounding("Miss 205723 m.", DRAFT).ok
    assert not check_grounding("Relative speed 120500 m/s.", DRAFT).ok


def test_an_identifier_grounds_a_mention_of_itself_whole():
    text = "DRAFT: MANEUVER on 99001-99118-20260924T205723 (object 99118), against CDM EX-RED-03-20260923T120500."
    assert check_grounding(text, DRAFT).ok
    assert not check_grounding("Against CDM EX-RED-03-20260923T120501.", DRAFT).ok, "a near miss is not a mention"


def test_a_queued_records_hash_and_the_summary_only_event_ids_ground_nothing():
    facts = {"count": 1, "queue": [{"event_id": "E1", "sha": "9c41e0aa13f2b7d4", "bytes": 2961,
                                    "class": "P1_URGENT", "eta_s": 1.4}],
             "summary_only_ids": ["99001-99412-20260925T075723"]}
    assert check_grounding("E1 (P1_URGENT): 2,961 bytes, ETA 1.4 s. Summary only: 99001-99412-20260925T075723.", facts).ok
    assert not check_grounding("ETA 41 s.", facts).ok
    assert not check_grounding("ETA 13 s.", facts).ok
    assert not check_grounding("75723 bytes waiting.", facts).ok


def test_absurd_exponents_never_crash_the_guard():
    """Hashes in evidence ('...94e9325680...') and overflowing numbers in an
    answer are data, not errors: the guard must still return a verdict."""
    evidence = {"inputs_hash": "0841199130007299069d1dae76e754e7fdf2240893608b5f94e9325680a0b806", "pc": 3.6e-5}
    assert check_grounding("Pc 3.6×10⁻⁵", evidence).ok
    result = check_grounding("Pc 1e999", evidence)
    assert not result.ok and result.unsupported == ["1e999"]
