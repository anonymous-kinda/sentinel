"""AI tier policy (ADR-007): a pure function of measured state.

Assumption, stated: an edge's route to a hosted AI service is the same
constrained link it uses to reach its hub, so the measured hub-link state
stands in for WAN state.

Hosted AI sends the operator's question and a tool's facts to a commercial
service, so the marking must say that content may go there. Only an exact
allow-listed marking does. Starting with UNCLASSIFIED is not enough: a
dissemination control or caveat (CUI, FOUO, NOFORN, PROPIN, ...) limits who
may receive the content, and a hosted service is a recipient no caveat
names. EXERCISE says what the data is for, not who may read it, and it is
the banner this demonstrator ships with. Anything else, including a marking
this list has never heard of, keeps the assistant on the node.
"""

from __future__ import annotations

import dataclasses

ROUTABLE_LINKS = {"CONNECTED", "DEGRADED", "LIMITED"}       # Jev: small answers
PROSE_LINKS = {"CONNECTED", "DEGRADED"}                     # hosted LLM: kilobytes of text
HOSTED_MARKINGS = ("UNCLASSIFIED", "UNCLASSIFIED // EXERCISE")
MARKING_NOT_CLEARED = (
    f"Marking not cleared for hosted AI (only {' or '.join(HOSTED_MARKINGS)}, with no caveat): "
    "hosted AI services are not used"
)


def canonical_marking(marking: str) -> str:
    """The words of a banner marking. Case and the spacing around // are how
    it was typed; they are not part of what it says."""
    return " // ".join(" ".join(part.split()) for part in marking.upper().split("//"))


_CLEARED = frozenset(canonical_marking(m) for m in HOSTED_MARKINGS)
QUESTION_HOLDS_POSITION = "The question holds a position: it is routed and phrased on this node only (ADR-010)"


@dataclasses.dataclass(frozen=True)
class TierInputs:
    link_state: str
    marking: str
    jev_configured: bool
    claude_configured: bool
    cloud_opt_in: bool
    question_holds_position: bool = False


@dataclasses.dataclass(frozen=True)
class TierDecision:
    router: str      # "jev" | "deterministic"
    narrator: str    # "claude" | "template"
    reason: str


def _hosted_allowed(inputs: TierInputs) -> str | None:
    """None if hosted AI may be used at all; otherwise why not."""
    if canonical_marking(inputs.marking) not in _CLEARED:
        return MARKING_NOT_CLEARED
    if not inputs.cloud_opt_in:
        return "Hosted AI not approved on this node"
    if inputs.question_holds_position:
        return QUESTION_HOLDS_POSITION
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
