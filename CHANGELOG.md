# Changelog

Notable changes to Sentinel, newest first. A version is `sentinel.__version__`,
and release bundles are named after it. Sentinel is a demonstrator: read the
README's [Limits](README.md#limits) before any claim below.

## [0.3.0] - 2026-09-24

A checkpoint. Every milestone of the build plan is in, and a full code review
found bugs that are fixed here. Each fix was proven by a test that failed first.

### Added

- **Operator console** (`web/`): events sorted by time to the maneuver commit
  point, a globe, and the B-plane view and Pc-against-covariance-scale curve
  driven by one slider. Every Pc renders through `PcValue`, with its method.
- **Hub and edge over a degraded link**, on real processes:
  - NATS leafnodes between the nodes (ADR-004);
  - priority pull by maneuver deadline (ADR-006, ADR-008);
  - a signed CRDT decision log (ADR-005);
  - link-state measurement;
  - six harness scenarios, reported in `docs/ddil-results.md`.
- **Army overhead-pass module** (ADR-010, ADR-011): pass windows and
  unobserved gaps, computed at the edge from public element sets. The unit's
  position never leaves that node. Two providers pass one conformance suite.
- **Demonstration-mode screening** from element sets: geometry only, with
  the Pc refused (ADR-002).
- **AI assistant, built as a safety pattern** (ADR-007):
  - Jev routes, code computes, Claude phrases, and the operator confirms;
  - the tier follows the link and the marking;
  - a number-grounding guard and a hash-chained audit;
  - `make ai-live-check` for when keys are set.
- **Signed supply chain** (ADR-012):
  - keyless signing, verified offline against a pinned trust root;
  - SBOMs and VEX statements;
  - an offline installer that refuses any file the signed checksums do not list.
- **Compliance evidence:** an OSCAL package generated from test evidence, and
  a DISA Ubuntu 24.04 STIG role. No ATO is claimed.
- **Requirements and interfaces:**
  - SysML v2 requirements with a generated trace;
  - ICDs (OpenAPI, AsyncAPI, the CDM profile, the sync envelope), each held
    to the code by a test;
  - doc drift guards and a registry of quoted numbers.
- **Program documents:** a white paper, a quad chart, a demo script, a
  disconnected-site install guide and a technical guide.
- **A Docker Compose stack.** It has not yet run in a container.
- **A codebase tutorial** (`docs/tutorial/`): fourteen chapters, one per subsystem,
  each with commands to run and questions with answers.
- **`.env` for local keys:** the hosted-AI commands and the demo read it,
  and an exported variable wins.

### Changed

- **The docs lead with what each reader gets:** the README, white paper and
  quad chart for an operator or program office; the guide, ADRs and ICDs for
  engineers. Every ADR states what it buys and what it costs.
- **VERIFIED means the edge reproduced the hub's result,** field by field,
  not only that it had the same inputs.
- **The LIMITED comparison is now fair and repeatable.** Every mode runs on
  the same shaped link from the same backlog, and the report gives medians of
  repeated runs.

### Fixed

- **Risk engine:** a covariance too small, or too large, to integrate in double
  precision is refused (`UNRESOLVED_INTEGRAL`, `INVALID_COVARIANCE`). Neither
  raises, and neither returns a plausible but wrong Pc.
- **Ingest:**
  - hostile and physically impossible CDMs are quarantined with a reason,
    including the new `IMPLAUSIBLE_STATE`;
  - an event holds a single data class, so a screening CDM never replaces a
    real Pc.
  - the plausible-radius bound is 3 million km, so a spacecraft on a Sun–Earth
    L1 or L2 orbit is admitted.
- **Sync:**
  - the edge admits only the bytes it asked for;
  - one bad record or manifest entry no longer blocks the rest;
  - manifests and operator-data backlogs now cross a LIMITED link;
  - admission control reads the clock per record.
- **Operator data:**
  - forgeries and malformed signatures are rejected, not raised;
  - an exchange costs what is sent, not the history a peer claims;
  - each rejection is recorded once.
- **Node:**
  - a torn audit line breaks the chain, not the node;
  - the event stream closes a lagging subscriber instead of silently dropping
    events;
  - write routes enforce read-only mode, a body limit and JSON shape in one
    place.
- **Console:**
  - the live stream reconnects and refetches;
  - one event's data never shows under another's name;
  - the classification marking is never assumed.

### Known gaps

The open gaps are listed in `SECURITY.md`:

- operator authentication (IA-2);
- TLS on the hub-to-edge link (SC-8);
- AI-audit truncation while the node is stopped (AU-9);
- unsigned annotations.

## [0.2.0] - 2026-09-23

- The risk engine is validated against NASA CARA's published cases, with a
  CDM codec and the curvature gate.
