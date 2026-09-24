"""Sentinel's OSCAL compliance package: CI evidence in, governed artifacts out.

    sources/*.toml     authored: tailoring, implementation statements, STIG decisions
    vendor/            upstream NIST catalog and DISA STIG, unmodified, checksummed
    oscal/             compliance-trestle workspace; every JSON document is generated

The generator (`scripts/oscal_evidence.py`) turns the authored sources into a
profile, component definition, SSP and assessment plan, and turns CI evidence
(pytest JUnit XML, DDIL harness results, OpenSCAP results) into assessment
results and a POA&M. Nothing under `oscal/` is edited by hand.
"""
