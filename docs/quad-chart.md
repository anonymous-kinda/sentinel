# Quad chart

A one-page summary of Sentinel in the standard four quadrants, for a program office or operations staff. It prints on one US-letter page (landscape) and uses system fonts only. The companion documents are the [white paper](white-paper.md), the [demo script](demo-script.md) and the [install guide](install-guide.md).

![Sentinel quad chart in four quadrants. Operational capability: a hub and a forward edge node joined by a measured leaf link, with CDMs flowing to the edge urgent first and signed decisions both ways. Technical approach and discriminators: open CCSDS standards, a NASA-validated risk engine that refuses unsupported numbers, priority sync, AI that cannot compute, and offline signature verification. Status and milestones: six items built, the requirement trace and security package partial, and a release, CDM feed, operator login, link TLS and an ATO still open. Evidence and next steps: measured results, the make targets that reproduce them, what fielding needs, and the demo hub's cost.](quad-chart.svg)

Sentinel is an open-source demonstration. It is not fielded, accredited or endorsed.

## Where the numbers come from

Every number on the chart comes from a generated report: the [validation report](validation-report.md), the [DDIL results](ddil-results.md), the [AI routing eval](ai-eval.md) and the [requirements trace](traceability.md). There are two exceptions, and each names its source:

- the AWS demo hub's monthly cost, from [deploy-aws.md](deploy-aws.md);
- the security control counts, from [compliance.md](compliance.md), which `tests/compliance/test_package_integrity.py` checks against the generated system security plan.

No cost estimate is given for fielding. `tests/docs/test_quad_chart.py` parses the chart and fails on any number that is neither in a generated report nor in its short allowlist, which records the source and the reason for each exception.

## Text version

For readers who cannot see the chart.

**Operational capability.** A hub (operations center) and an edge (forward node) are joined by a leaf link whose state each node measures: CONNECTED, DEGRADED, LIMITED or DENIED. CDMs flow to the edge, the most urgent first. Signed decisions flow both ways. Each node serves its own console from its own data.

- Decide before the maneuver commit point whether to maneuver.
- A Pc the method cannot support is refused, and dilution is flagged.
- Cut off, each node keeps working, and urgent data crosses first when the link returns.
- AI routes and phrases, validated code computes, and a person decides.
- A ground unit sees when public imagers can observe it, and its position never leaves its edge node.

**Technical approach and discriminators.** CCSDS standards at every seam. A Foster-Estes 2D Pc ported from NASA CARA, with the worst case and a dilution flag. Priority sync and loss-free merging of operator data. An AI tier set by the measured link, the marking and opt-in, with no code path to the maths. A bundle verified offline before it is unpacked. Alternatives often print a Pc from element sets, read a low Pc as safety, let the last writer win, or rely on a hosted service.

**Status and milestones.** Built: the risk engine, the console, hub/edge sync (six scenarios on real processes), AI decision support, the pass module with its OPSEC scenario, and the signed bundle. Partial: the requirement trace and the OSCAL package. Open: a first signed release, CI on a hosted service, a real CDM feed, operator login, TLS on the leaf link and an ATO.

**Evidence and next steps.** The measured results are in the reports above. Reproduce them with `make report`, `make ddil`, `make opsec`, `make airgap-selftest` and `make trace`. Fielding needs real CDM access, operator authentication, TLS on the leaf link, packaged hub and edge messaging, and an authorization to operate.
