"""The subject namespace (sentinel/bus/subjects.py): one door, so the message
bus ICD (docs/icd/asyncapi.yaml) can be checked against it."""

import pytest

from sentinel.bus import subjects


def test_a_node_event_is_scoped_to_its_node_and_named_by_its_kind():
    assert subjects.local("edge-1", "sync.progress") == "node.edge-1.sync.progress"
    assert subjects.cdm_rejected("hub") == "node.hub.cdm.rejected"


def test_an_accepted_cdm_is_published_per_event():
    assert subjects.cdm_accepted("hub", "99001-99118-20260924T200000") == (
        "node.hub.cdm.accepted.99001-99118-20260924T200000"
    )


def test_a_value_becomes_exactly_one_subject_token():
    assert subjects.cdm_accepted("hub a", "X.Y>*") == "node.hub_a.cdm.accepted.X_Y__"


def test_a_node_event_kind_the_icd_does_not_describe_is_refused():
    with pytest.raises(ValueError, match="unregistered node event kind"):
        subjects.local("hub", "made.up")
