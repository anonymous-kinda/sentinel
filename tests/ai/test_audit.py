"""Hash-chained audit log for AI interactions (AU-9, AU-10).

The assistant writes one JSON line per question asked (with its tier, route,
grounding result and answer) and one per draft confirmed. Each line's hash
covers the previous line's hash, so editing or deleting any line breaks
verification from that line on. Truncating the newest lines is not detected
by the chain alone (POA&M, AU-9).
"""

import json

from sentinel.audit import AuditLog

GENESIS = "0" * 64


def test_records_form_a_chain(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    a = log.append({"kind": "ask", "text": "which events need action"}, at="2026-09-23T00:00:00Z")
    b = log.append({"kind": "route", "tool": "list_events"}, at="2026-09-23T00:00:01Z")
    assert a["seq"] == 0 and a["prev"] == GENESIS
    assert b["seq"] == 1 and b["prev"] == a["hash"]
    assert log.verify().ok


def test_log_survives_reload_and_still_verifies(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(5):
        log.append({"kind": "note", "i": i}, at=f"t{i}")
    reloaded = AuditLog(path)
    assert len(reloaded.entries()) == 5
    assert reloaded.verify().ok
    assert reloaded.append({"kind": "note", "i": 5}, at="t5")["prev"] == reloaded.entries()[-2]["hash"]


def test_editing_a_line_is_detected_at_that_line(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(4):
        log.append({"kind": "note", "i": i}, at=f"t{i}")
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[2])
    tampered["i"] = 99
    lines[2] = json.dumps(tampered, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    result = AuditLog(path).verify()
    assert not result.ok and result.first_bad == 2


def test_deleting_a_line_is_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(4):
        log.append({"kind": "note", "i": i}, at=f"t{i}")
    lines = path.read_text().splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n")
    result = AuditLog(path).verify()
    assert not result.ok and result.first_bad == 1


def test_in_memory_log_for_tests_and_ephemeral_nodes():
    log = AuditLog(None)
    log.append({"kind": "ask"}, at="t")
    assert log.verify().ok and len(log.entries()) == 1
