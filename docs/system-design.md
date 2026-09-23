# Sentinel — System Design v0.1

**A DDIL-resilient conjunction assessment decision aid for satellite operators.**

Status: Draft. This document is the design spine. The technical guide derives from it; the white paper derives from the technical guide. Nothing gets coded until the relevant ADR here is marked Accepted.

---

## 1. Problem Statement

A satellite operator receives a stream of Conjunction Data Messages warning that a tracked object may pass dangerously close to one of their assets. Each event arrives not once but as a sequence, reissued as new tracking refines the state estimate. The operator must decide — before the maneuver commit point — whether to burn propellant to avoid it.

Two things make this hard in practice:

**The math is deceptive.** A low probability of collision can mean "we know precisely that these objects will miss" or "we know so little that the probability is smeared thin across a huge uncertainty volume." These are opposite situations that produce similar numbers. NASA CARA documents that in this dilution region, inflating covariance by one order of magnitude drops Pc by two — safety appears to improve as data quality degrades.

**The tooling assumes connectivity.** Conjunction assessment tooling is overwhelmingly cloud-hosted and API-driven. An operator working from a deployed ground station, a ship, or any environment with a denied or degraded link loses the decision aid exactly when the decision still has to be made. The commit point does not move because the network went down.

Sentinel addresses both: a decision aid that computes collision risk honestly — including flagging when the number cannot be trusted — and that continues functioning through denied, degraded, intermittent, and bandwidth-limited operation.

### Non-goals

Sentinel is not an operational flight safety system and will not be represented as one. It does not perform orbit determination, does not produce a maneuver plan suitable for uplink, and does not replace 19 SDS screening. It is a decision *aid* demonstrating an architecture.

---

## 2. Design Principles

These are the tiebreakers. When two designs are otherwise equal, the one that better serves a principle higher in this list wins.

1. **Degrade, never fail.** Every component has a defined behavior when its dependencies are unreachable. A component that requires connectivity is not a field tool.
2. **The math is auditable.** Every risk number Sentinel displays can be traced to its inputs and the algorithm that produced it. No black boxes in the decision path.
3. **Honest about uncertainty.** Where a computed value is unreliable, Sentinel says so rather than displaying it with false confidence. Dilution-region flagging is a first-class feature, not a footnote.
4. **Standards at the seams.** Interfaces between modules use open, published standards — CCSDS message formats, not bespoke schemas. This is what makes the architecture modular rather than merely decomposed.
5. **The AI drafts, the operator decides, the code computes.** A language model may translate intent and summarize findings. It never produces a risk number and never takes a consequential action without confirmation.

---

## 3. Architecture Decision Records

Each ADR states a decision, why, and what was rejected. Rejected alternatives are recorded because the reasoning is the deliverable — anyone can pick NATS, the value is in being able to say why not Kafka.

### ADR-001 — CDM as the canonical internal data contract

**Status:** Accepted

**Decision.** Every conjunction that enters Sentinel is normalized to a CCSDS 508.0-B-1 Conjunction Data Message representation, regardless of source. Internal modules consume CDMs. Nothing downstream of ingest knows where the data came from.

**Rationale.** This is the single decision that makes everything else modular. Source adapters become interchangeable, the risk engine has exactly one input format, and the interface is a published international standard rather than something invented for this project — which is the substantive meaning of a modular open systems approach, as opposed to just having separate files.

It also solves the data-access risk. Space-Track CDM access may not be granted. Wayfinder access costs money. CelesTrak provides elements, not CDMs. Because all three normalize to the same contract, the project proceeds regardless of which materializes, and switching is an adapter, not a rewrite.

**Rejected.** A bespoke internal JSON schema, simpler to write and worthless as a MOSA demonstration. Passing raw source-specific payloads through, which couples every downstream module to every data source.

**Consequence.** Where Sentinel derives conjunctions from element sets rather than receiving real CDMs, it must synthesize a CDM and mark it as derived. Fields that cannot be honestly populated — notably real covariance — are left absent rather than filled with plausible values. See ADR-002.

---

### ADR-002 — Two screening modes, explicitly labeled

**Status:** Accepted

**Decision.** Sentinel operates in one of two modes, displayed prominently in the interface and stamped on every output.

*Demonstration mode* screens from public element sets using SGP4 propagation. It produces miss distances and geometry. **It does not produce a probability of collision**, because there is no covariance to compute one from.

*Assessment mode* consumes real CDMs with covariance and computes Pc using the methods in ADR-003.

**Rationale.** NASA CARA's position is unambiguous — their 2022 best-practices briefing states that TLEs are not sufficient for conjunction assessment, that kilometer-scale theory error is too large for maneuver planning, and that no covariance is available to compute a collision probability. A project that screens on TLEs and reports a Pc anyway is either uninformed or dishonest, and a reviewer who knows the domain will spot it immediately.

Building the limitation into the architecture inverts this. The constraint becomes evidence of domain understanding rather than a flaw to be hidden.

**Rejected.** Single-mode operation with caveats in the README. Caveats in a README do not appear next to the number on the screen.

---

### ADR-003 — Reimplement Foster-Estes 2D Pc in Python; Orekit as the reference oracle

**Status:** Proposed — pending Orekit footprint evaluation

**Decision.** The primary risk engine is a Python implementation of the Foster-Estes 2D collision probability method, ported from NASA CARA's publicly released MATLAB and validated against their published test cases. Orekit via its Python wrapper serves as an independent implementation to check against, not as the runtime dependency at the edge.

Alongside Pc, the engine computes maximum Pc by covariance contraction and flags events sitting in the dilution region.

**Rationale.** CARA's tools are MATLAB and are explicitly published as building blocks for reimplementation, not as a library. Porting them is the intended use, and the port is the part of this project that demonstrates first-principles command of the domain rather than library plumbing. Validating against their published cases turns "I implemented a paper" into "I implemented a paper and proved it correct."

Orekit is the most mature open-source flight dynamics library and has Pc implementations built in, but it carries a JVM. At the edge, that footprint has to be justified. Using it as a test oracle gets the validation benefit without the deployment cost.

**Rejected.** Depending on Orekit at runtime — defensible, but it makes the interesting part of the project someone else's code. Calling out to MATLAB — not deployable. Using a third-party Python Pc implementation — none with comparable provenance exists.

**Open question.** Whether Orekit-python installs cleanly enough in CI to be a practical oracle. If it does not, fall back to validating against CARA's published numerical results alone.

---

### ADR-004 — Modular monolith with an internal event bus

**Status:** Accepted

**Decision.** Sentinel is a single deployable binary internally structured as event-driven modules communicating over NATS JetStream. The same modules can be split into separate services in a cloud deployment without changing module code.

**Rationale.** The job description names microservices, event-driven architectures, and modular monoliths in one sentence, which is a hint that the interesting answer is understanding when each applies. The honest answer for an edge-deployable system is both: microservice decomposition in the cloud where orchestration is free, single-binary at the edge where it is not.

NATS is a small single binary with no external dependencies. Critically, its leaf node model with local JetStream storage provides durable messaging that survives disconnection and reconciles on reconnect — which is the sync problem in ADR-005, solved at the transport layer rather than in application code.

**Rejected.** Kafka — requires a JVM and coordination quorum, which does not fit on constrained edge hardware and does not survive isolation gracefully. Redpanda — Kafka-compatible and lighter, still heavier than needed and with no comparable disconnected-leaf story. Plain MQTT — light enough but no durable stream semantics. Direct function calls with no bus — simplest, but forecloses the cloud decomposition that is half the argument.

---

### ADR-005 — Delta-state CRDTs for operator-generated data

**Status:** Proposed

**Decision.** Operator annotations, triage decisions, risk-tolerance settings, and the decision log replicate as delta-state CRDTs. Ingested reference data — CDMs, ephemeris — does not; it is immutable and replicates by store-and-forward replay.

**Rationale.** These two data classes have opposite requirements and conflating them is the common design error. Reference data is append-only and authored upstream, so it needs durable replay, not merge. Operator data is authored concurrently at multiple disconnected nodes and genuinely conflicts.

State-based CRDTs are chosen over operation-based specifically because they tolerate lost, duplicated, and reordered delivery, which is the DDIL environment by definition. Operation-based CRDTs require reliable causal delivery — an assumption that is exactly what a denied link removes. Delta encoding keeps the payload from growing unboundedly.

The model follows TAK's DataSync approach: mission data held server-side, clients synchronizing what they missed while disconnected. This is worth citing directly, because it is the pattern the customer already trusts.

**Rejected.** Last-write-wins on a timestamp — silently destroys an operator's work, unacceptable in a decision log. Operation-based CRDTs — wrong delivery assumptions. Manual conflict resolution — moves the problem to the operator at the worst possible moment.

---

### ADR-006 — Bandwidth triage by decision urgency

**Status:** Proposed

**Decision.** When bandwidth is constrained, sync priority is ordered by time-to-maneuver-commit-point and risk, not by recency or arrival order. High-Pc events approaching their commit point transit first. Routine catalog refresh transits last, or not at all.

**Rationale.** This is the design decision most likely to come up in a customer conversation, because it is where the architecture demonstrably encodes mission understanding rather than engineering preference. Every system claims to prioritize; the question is by what. Sorting by operational consequence — how soon does someone have to act, and how badly — is a different answer from sorting by timestamp, and it is the right one.

**Open question.** Behavior when the link is so degraded that even priority traffic cannot complete. Proposal: transmit a degraded event summary — identifiers, TCA, risk band, no covariance — sized to fit, with full CDMs queued behind it. Needs sizing analysis against a realistic constrained-link budget.

---

### ADR-007 — AI layer is advisory, tool-constrained, and locally runnable

**Status:** Proposed

**Decision.** Natural language input is translated by a language model into calls against a typed, validated internal API. The model never computes risk, never writes to the decision log without confirmation, and never takes an action with operational consequence. Every prompt, tool call, and result is logged. A small quantized model runs locally so the capability survives disconnection; when unavailable, the interface falls back to deterministic controls with no loss of function.

**Rationale.** DoD's AI ethical principles require traceability, reliability, and governability, and CDAO's responsible AI tooling operationalizes them. The architecture satisfies these by construction rather than by policy assertion: the model cannot produce an untraceable number because it has no path to the math.

This also happens to be the correct engineering choice independent of policy. Deterministic computation belongs in code.

**Rejected.** Free-form query generation against the data store — unauditable and unbounded. Cloud-hosted inference only — fails the core premise. No AI layer — leaves a named requirement unaddressed.

---

## 4. Core Pipeline

```
  SOURCE ADAPTERS          NORMALIZATION         RISK ENGINE
  ┌──────────────┐        ┌──────────────┐      ┌──────────────┐
  │ Space-Track  │───┐    │              │      │ Foster-Estes │
  │ Wayfinder    │───┼───▶│  CDM (CCSDS  │─────▶│ 2D Pc        │
  │ CelesTrak+GP │───┘    │  508.0-B-1)  │      │ Max Pc       │
  └──────────────┘        │              │      │ Dilution flag│
         │                └──────────────┘      └──────────────┘
         │                       │                      │
         │                       ▼                      ▼
         │                ┌──────────────────────────────────┐
         │                │      NATS JetStream (local)      │
         │                └──────────────────────────────────┘
         │                       │              │           │
         ▼                       ▼              ▼           ▼
  ┌──────────────┐        ┌───────────┐  ┌───────────┐ ┌──────────┐
  │ Store &      │        │ Triage /  │  │ Decision  │ │ AI query │
  │ forward queue│        │ ranking   │  │ log (CRDT)│ │ (local)  │
  └──────────────┘        └───────────┘  └───────────┘ └──────────┘
         │                                      │
         └──────────── SYNC LAYER ──────────────┘
                   (priority by ADR-006)
```

The seam that matters is between normalization and everything downstream. Above it, source-specific. Below it, nothing knows or cares where a CDM came from. That seam is the modular system interface, and it is defined by a published standard rather than by Sentinel.

---

## 5. Module Interfaces

Each is a modular system interface in the MOSA sense — a boundary that could be independently reimplemented or competed.

| Interface | Contract | Standard basis |
|---|---|---|
| Source → Normalization | Source-native payload | Vendor/agency API |
| Normalization → Risk | CDM | CCSDS 508.0-B-1 |
| Risk → Triage | Assessed conjunction (CDM + Pc + flags) | CDM extension |
| Any → Sync | Prioritized replication envelope | Local; DTN-influenced |
| Operator ↔ Decision log | CRDT delta | Local |

The sync envelope is the one interface without a standards basis. It is influenced by Bundle Protocol's store-carry-forward semantics without implementing BPv7 — worth stating plainly rather than overclaiming, and worth noting that DTN originated in space communications, which is a genuinely apt pedigree to cite.

---

## 6. Validation Strategy

The project is only credible if the math is provably right, so validation is a deliverable, not a phase.

**Risk engine.** Unit tested against NASA CARA's published test cases. Cross-checked against Orekit where feasible. Dilution-region detection tested against constructed cases where inflating covariance lowers Pc — demonstrating the flag fires on exactly the pathology it exists to catch.

**DDIL behavior.** A reproducible test harness using traffic control emulation and fault injection, running named scenarios as CI jobs rather than manual demonstrations:

- *Denied* — total isolation for six hours, then reconnect. Assert no data loss, correct merge, priority-ordered catch-up.
- *Degraded* — sustained packet loss and high latency. Assert continued operation.
- *Intermittent* — repeated short drops. Assert no duplicate decision log entries.
- *Limited* — hard bandwidth cap at satellite-link rates. Assert priority ordering holds and degraded summaries transit.

The recorded output of the Denied scenario is the single most persuasive artifact this project will produce. It should be captured as a short clip.

---

## 7. Open Questions

1. Does Space-Track CDM-class access get granted? Gates demonstration versus assessment mode as the default.
2. Orekit-python CI viability (ADR-003).
3. Degraded-summary sizing against a realistic link budget (ADR-006).
4. Which quantized model is small enough for the target edge profile while still reliable at tool-calling (ADR-007).
5. Whether the TraCSS transition changes CDM access mechanics during the build window.

---

## 8. Document Trail

| Artifact | Derives from | Audience |
|---|---|---|
| This design | Research report | Self, technical reviewers |
| Technical guide | This design | Engineers reading the repo |
| White paper | Technical guide | Acquisition, operational, executive |
| SysML v2 model | This design | MBSE demonstration |
| OSCAL draft SSP | Implementation | Security/ATO reviewers |

Written once, derived three times. The white paper is not a separate research effort; it is this document retargeted at a reader who cares about mission outcome and risk rather than about NATS.
