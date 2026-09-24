"""SECURITY.md is ready to publish: a private reporting channel, no placeholders."""

import pathlib

POLICY = (pathlib.Path(__file__).resolve().parent.parent / "SECURITY.md").read_text()


def test_the_policy_names_a_private_reporting_channel():
    assert "MAINTAINER:" not in POLICY, "a placeholder would ship in the public repo"
    assert "private vulnerability reporting" in POLICY.lower()
    assert "Report a vulnerability" in POLICY, "the button a reporter looks for"
