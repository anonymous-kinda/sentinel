"""AI tier policy (ADR-007): a pure function of measured state.

Assumption, stated: an edge's route to a hosted AI service is the same
constrained link it uses to reach its hub, so the measured hub-link state
stands in for WAN state.
"""

from __future__ import annotations

import dataclasses

ROUTABLE_LINKS = {"CONNECTED", "DEGRADED", "LIMITED"}       # Jev: small answers
PROSE_LINKS = {"CONNECTED", "DEGRADED"}                     # hosted LLM: kilobytes of text


@dataclasses.dataclass(frozen=True)
class TierInputs:
    link_state: str
    marking: str
    jev_configured: bool
    claude_configured: bool
    cloud_opt_in: bool


@dataclasses.dataclass(frozen=True)
class TierDecision:
    router: str      # "jev" | "deterministic"
    narrator: str    # "claude" | "template"
    reason: str


def _hosted_allowed(inputs: TierInputs) -> str | None:
    """None if hosted AI may be used at all; otherwise why not."""
    if not inputs.marking.upper().startswith("UNCLASSIFIED"):
        return "Classified marking: hosted AI services are not used"
    if not inputs.cloud_opt_in:
        return "Hosted AI not approved on this node"
    return None


def decide(inputs: TierInputs) -> TierDecision:
    blocked = _hosted_allowed(inputs)
    if blocked:
        return TierDecision("deterministic", "template", blocked)
    if inputs.link_state not in ROUTABLE_LINKS:
        return TierDecision("deterministic", "template", f"Link {inputs.link_state}: local routing only")

    router = "jev" if inputs.jev_configured else "deterministic"
    narrator = "claude" if inputs.claude_configured and inputs.link_state in PROSE_LINKS else "template"
    if inputs.link_state == "LIMITED" and router == "jev":
        reason = "Link LIMITED: Jev routes (its answer is a few probabilities); prose stays local"
    elif router == "deterministic":
        reason = "Jev not configured: local routing"
    else:
        reason = f"Link {inputs.link_state}: hosted routing and narration available"
    return TierDecision(router, narrator, reason)
