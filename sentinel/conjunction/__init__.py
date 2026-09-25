"""Mission module: conjunction assessment.

Consumes CDMs (the ADR-001 contract), assesses them with sentinel.risk,
groups updates into events, and reduces each event to a summary for edges
(summaries.py). The summary carries the event's deadline (the maneuver
commit point) and consequence level; the sync agent derives the priority
class from those itself (SyncAgent._wanted in sentinel/sync/agent.py).
"""
