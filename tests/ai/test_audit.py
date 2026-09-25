"""Hash-chained audit log for AI interactions (AU-9, AU-10).

The assistant writes one JSON line per question asked (with its tier, route,
grounding result and answer) and one per draft confirmed. Each line's hash
covers the previous line's hash, so editing or deleting any line breaks
verification from that line on. Truncating the newest lines is not detected
by the chain alone (POA&M, AU-9).

The file is the record: `verify` reads it from disk every time, and holds it
against the hashes this process wrote, so a change made while the node runs
is found. A line that cannot be read (a write torn by a power cut) breaks
the chain at that line; it never stops the node.
"""

import json
import logging

import pytest

from sentinel.audit import AuditLog, VerifyResult
from sentinel.audit.chain import _digest

GENESIS = "0" * 64
# What a power cut in the middle of a write leaves: a line with no end.
TORN = b'{"at":"t3","kind":"note","prev":"'


def chain_of(path, n: int) -> AuditLog:
    log = AuditLog(path)
    for i in range(n):
        log.append({"kind": "note", "i": i}, at=f"t{i}")
    return log


def broken_reports(caplog) -> list[dict]:
    return [r.fields for r in caplog.records if r.getMessage() == "Audit chain broken"]


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


# ------------------------------------------------------ an unreadable line
@pytest.mark.parametrize("bad", [TORN, b"[1, 2]", b"\xff\xfe not text"], ids=["torn", "not-an-object", "not-utf8"])
def test_an_unreadable_line_breaks_the_chain_there_instead_of_stopping_the_node(tmp_path, caplog, bad):
    path = tmp_path / "audit.jsonl"
    chain_of(path, 3)
    with path.open("ab") as f:
        f.write(bad)
    log = AuditLog(path)
    assert log.verify() == VerifyResult(False, 4, 3)
    assert {"first_bad": 3, "count": 4} in broken_reports(caplog)


def test_a_broken_chain_is_logged_once_not_on_every_verify(tmp_path, caplog):
    path = tmp_path / "audit.jsonl"
    chain_of(path, 2)
    with path.open("ab") as f:
        f.write(TORN)
    log = AuditLog(path)
    log.verify()
    log.verify()
    assert len(broken_reports(caplog)) == 1


def test_an_entry_after_a_torn_line_is_kept_and_the_chain_never_verifies_again(tmp_path):
    """Appending goes on: the assistant's asks and confirms are still recorded.
    The torn bytes stay on their own line as evidence, the new entry links to
    the last readable one, and the break is reported at the torn line forever."""
    path = tmp_path / "audit.jsonl"
    chain_of(path, 3)
    with path.open("ab") as f:
        f.write(TORN)
    log = AuditLog(path)
    last_readable = log.entries()[-1]
    entry = log.append({"kind": "note", "i": 4}, at="t4")

    lines = path.read_bytes().split(b"\n")
    assert lines[3] == TORN, "the torn bytes are kept, never repaired"
    assert json.loads(lines[4]) == entry
    assert entry["seq"] == 4 and entry["prev"] == last_readable["hash"]
    assert log.verify() == VerifyResult(False, 5, 3)
    assert AuditLog(path).verify() == VerifyResult(False, 5, 3)
    assert [e["seq"] for e in AuditLog(path).entries()] == [0, 1, 2, 4]


# ------------------------------------------------- changed while running
def test_verify_reads_the_file_so_an_edit_while_running_is_found(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = chain_of(path, 4)
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[2])
    tampered["i"] = 99
    lines[2] = json.dumps(tampered, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    assert log.verify() == VerifyResult(False, 4, 2)
    assert log.entries()[2]["i"] == 99, "the record served is the file, as verified"


def test_deleting_the_newest_line_while_running_is_found(tmp_path):
    """The chain alone cannot see a shorter file; the node holds the hashes it
    wrote, so while it runs the missing line is named."""
    path = tmp_path / "audit.jsonl"
    log = chain_of(path, 4)
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:3]) + "\n")
    assert log.verify() == VerifyResult(False, 3, 3)


def test_rewriting_a_consistent_chain_while_running_is_found(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = chain_of(path, 4)
    forged, prev = [], GENESIS
    for i, line in enumerate(path.read_text().splitlines()):
        entry = json.loads(line)
        entry["i"] = 99 if i == 1 else entry["i"]
        entry["prev"] = prev
        entry["hash"] = prev = _digest(entry)
        forged.append(json.dumps(entry, sort_keys=True))
    path.write_text("\n".join(forged) + "\n")
    assert AuditLog(path).verify().ok, "the forgery is a valid chain on its own"
    assert log.verify() == VerifyResult(False, 4, 1)


def test_the_file_removed_while_running_is_found(tmp_path, caplog):
    caplog.set_level(logging.ERROR)
    path = tmp_path / "audit.jsonl"
    log = chain_of(path, 2)
    path.unlink()
    assert log.verify() == VerifyResult(False, 0, 0)
    assert broken_reports(caplog) == [{"first_bad": 0, "count": 0}]
