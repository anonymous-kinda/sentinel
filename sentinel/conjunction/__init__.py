"""Mission module: conjunction assessment.

Consumes CDMs (the ADR-001 contract), assesses them with sentinel.risk,
groups updates into events, and reduces each event to the mission-agnostic
triage key the sync layer orders by.
"""
