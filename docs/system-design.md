# Sentinel — System Design v0.1

**A DDIL-resilient conjunction assessment decision aid for satellite operators.**

Status: living design record; each ADR states its own status. This document is the design spine. The technical guide derives from it; the white paper derives from the technical guide. Nothing gets coded until the relevant ADR here is marked Accepted.

---

## 1. Problem Statement

A satellite operator receives a stream of Conjunction Data Messages warning that a tracked object may pass dangerously close to one of their assets. Each event arrives not once but as a sequence, reissued as new tracking refines the state estimate. The operator must decide — before the maneuver commit point — whether to burn propellant to avoid it.

Two things make this hard in practice:

**The math is deceptive.** A low probability of collision can mean "we know precisely that these objects will miss" or "we know so little that the probability is smeared thin across a huge uncertainty volume." These are opposite situations that produce similar numbers. Deep in this dilution region, a tenfold increase in position uncertainty cuts Pc about a hundredfold — safety appears to improve as data quality degrades.

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

**Status:** Accepted, implemented in `sentinel/cdm`.

**Decision.** Every conjunction that enters Sentinel is normalized to a CCSDS 508.0-B-1 Conjunction Data Message representation, regardless of source. Internal modules consume CDMs. Nothing downstream of ingest knows where the data came from.

**Rationale.** This is the single decision that makes everything else modular. Source adapters become interchangeable, the risk engine has exactly one input format, and the interface is a published international standard rather than something invented for this project — which is the substantive meaning of a modular open systems approach, as opposed to just having separate files.

It also solves the data-access risk. Space-Track CDM access may not be granted. Wayfinder access may not be available to this project. CelesTrak provides elements, not CDMs. Because all three normalize to the same contract, the project proceeds regardless of which materializes, and switching is an adapter, not a rewrite.

**Rejected.** A bespoke internal JSON schema, simpler to write and worthless as a MOSA demonstration. Passing raw source-specific payloads through, which couples every downstream module to every data source.

**Consequence.** Where Sentinel derives conjunctions from element sets rather than receiving real CDMs, it must synthesize a CDM and mark it as derived. Fields that cannot be honestly populated — notably real covariance — are left absent rather than filled with plausible values. See ADR-002.

---

### ADR-002 — Two screening modes, explicitly labeled

**Status:** Accepted

**Decision.** Sentinel operates in one of two modes, displayed prominently in the interface and stamped on every output.

*Demonstration mode* screens from public element sets using SGP4 propagation. It produces miss distances and geometry. **It does not produce a probability of collision**, because there is no covariance to compute one from.

*Assessment mode* consumes real CDMs with covariance and computes Pc using the methods in ADR-003.

**Rationale.** NASA CARA's position is unambiguous — its best-practices guidance states that TLEs are not sufficient for conjunction assessment, that kilometer-scale theory error is too large for maneuver planning, and that no covariance is available to compute a collision probability. A project that screens on TLEs and reports a Pc anyway is either uninformed or dishonest, and a reviewer who knows the domain will spot it immediately.

Building the limitation into the architecture inverts this. The constraint becomes evidence of domain understanding rather than a flaw to be hidden.

**Rejected.** Single-mode operation with caveats in the README. Caveats in a README do not appear next to the number on the screen.

**Implemented (2026-09-24).** `sentinel/screening` and `sentinel screen` screen one primary against public OMM element sets:
- SGP4 through Skyfield;
- an apogee/perigee pre-filter;
- range sampled every 60 s, with a bound that cannot drop an approach;
- each minimum refined with Brent's method.

Against brute-force sampling, the measured agreement is under a millisecond in TCA and under a centimetre in miss distance (`tests/screening/test_screen.py`). One primary against the other 166 objects in the bundled snapshot for 24 h takes about 0.1 s.

Each approach can be written as a DERIVED CDM with no covariance. When it is ingested, the engine's existing `NO_COVARIANCE` gate refuses the Pc. The refusal therefore holds by construction, and the engine has no screening code path. `.importlinter` forbids `sentinel.screening` from importing the engine.

---

### ADR-003 — Reimplement Foster-Estes 2D Pc in Python; NASA CARA's published cases as the oracle

**Status:** Accepted (2026-09-23). Orekit was dropped as the oracle; the reasons are below.

**Decision.** The primary risk engine is a Python implementation of the Foster-Estes 2D collision probability method, ported from NASA CARA's publicly released MATLAB. It is validated against values CARA itself published:
- the 53-event operational set in `DataFiles/PcTestCaseCDMs`, each with CARA's Pc2D, 3D Nc and usage-violation verdict;
- the Alfano (2009) benchmark CDMs;
- the Omitron unit-test cases.

Alongside Pc, the engine computes maximum Pc by covariance scaling and flags events sitting in the dilution region.

**Rationale.** CARA's tools are MATLAB and are explicitly published as building blocks for reimplementation, not as a library. Porting them is the intended use, and the port is the part of this project that shows first-principles command of the domain rather than library plumbing.

CARA publishes expected values for real conjunctions, including its own judgement of when the 2D method is invalid. That makes a third-party oracle unnecessary: the reference is the organisation whose method this is. Result (`docs/validation-report.md`): **53/53 operational events within 1.5e-8 relative**, and **zero** events where Sentinel returns a 2D Pc that CARA says 2D cannot handle.

**Rejected.**
- Depending on Orekit at runtime: defensible, but it makes the interesting part of the project someone else's code, and adds a JVM at the edge.
- Orekit as a test oracle: superseded, because CARA's published results are a stronger reference than a second independent implementation.
- Calling out to MATLAB: not deployable.
- A third-party Python Pc library: none with comparable provenance exists.

**Consequences found during validation.**
1. *TCA refinement.* CDM states sit at a TCA rounded to the millisecond. The engine refines both states to the true linear-motion closest approach, as CARA's `FindNearbyCA` does. It refuses only when the required shift exceeds 10 ms, which is 20× the largest rounding error and cannot be rounding.
2. *Miss-distance convention.* CARA's unadjusted methods take the full |r| as the in-plane miss. Sentinel takes the in-plane component at the refined TCA, which matches CARA's TCA-adjusted Pc2D. The 1.6e-4 difference on Omitron Case 2 is explained to 1e-14 by this convention (asserted in Tier 3).
3. *Applicability.* A relative-speed gate alone caught only 4 of the 29 events CARA flags. A second gate, `CURVILINEAR_UNCERTAINTY`, compares the bend of each object's 1-sigma along-track arc with the encounter plane's tightest sigma. It catches all 29, at the cost of 5 conservative refusals. The threshold was calibrated on the same set, and the report says so.
4. *Divergence kept on purpose.* For a non-positive-definite covariance, CARA repairs it and reports Pc = 0. Sentinel refuses: a repaired covariance is not the one the originator supplied.

---

### ADR-004 — Modular monolith with an internal event bus

**Status:** Accepted (2026-09-23). Amended after implementation; the amendments are marked below.

**Decision.** Sentinel is structured as event-driven modules that talk only through a `Bus` protocol: publish/subscribe plus request/reply. In one process the bus is in-memory. On a deployed node it is NATS: each node runs its own `nats-server`, and the server, not the application, holds the leafnode link to other nodes. The same module code runs in both.

**Rationale.** Microservices, event-driven architectures and modular monoliths are often offered as alternatives. The interesting answer is knowing when each applies. For an edge-deployable system the honest answer is both: decompose in the cloud where orchestration is free, and ship a single deployable at the edge where it is not.

A node's console, store and engine talk only to their *local* NATS server. So a denied link never breaks the node; the leaf reconnects by itself. The DENIED scenario measures this: 2.8 ms p95 console latency while the link is cut.

**Amendment: what NATS is used for.**
- Leafnode connectivity, request/reply, and compression (s2).
- Subject permissions, including OPSEC: a leaf never exports `unit.>` or `passes.>`.

JetStream is **not** used for replication. Priority is a mission concept that a stream mirror, which is FIFO, cannot express (ADR-008). Operator data is a durable CRDT whose state does its own store-and-forward (ADR-005). Using JetStream anyway would add a second, unmeasured ordering to explain.

**Amendment: "single binary".** A node is one signed bundle that runs two processes, `nats-server` and `sentinel`. That is stated plainly rather than hidden behind an embedded server.

**Rejected.**
- *Kafka:* needs a JVM and a coordination quorum, doesn't fit constrained edge hardware, and doesn't survive isolation gracefully.
- *Redpanda:* lighter, but no comparable disconnected-leaf story.
- *Plain MQTT:* no request/reply semantics and no leaf model.
- *Direct function calls with no bus:* forecloses the cloud decomposition that is half the argument.

---

### ADR-005 — State-based CRDTs for operator-generated data

**Status:** Accepted (2026-09-23), implemented in `sentinel/crdt` and `sentinel/ops`.

**Decision.** Operator annotations, triage status, and the decision log replicate as state-based CRDTs:
- **Decision log:** a grow-only log of immutable entries, each Ed25519-signed and hash-chained per node.
- **Annotations and triage status:** multi-value registers. Concurrent writes are all kept and shown as a CONFLICT.

Ingested reference data (CDMs) is immutable and replicates by priority pull (ADR-008), not by merge.

**Rationale.** These two data classes have opposite requirements, and conflating them is the common design error:
- **Reference data** is append-only and authored upstream. It needs ordered delivery, not merge.
- **Operator data** is authored concurrently at disconnected nodes, and genuinely conflicts.

State-based rather than operation-based CRDTs, because state-based merge tolerates lost, duplicated and reordered delivery, and that is the DDIL link. Anti-entropy is a single request/reply. It carries this node's causal contexts plus whatever the peer was last known to lack; a stale memory of the peer just means sending more.

**Evidence.**
- *Property tests* (Hypothesis, 150 random histories × 40 steps, three replicas, stale and duplicated payloads delivered in any order) prove:
  - convergence;
  - no lost or duplicated entries;
  - every write is either visible or was overwritten by someone who had seen it.
- *Integrity:* a tampered entry is rejected, and a reused dot with different content raises.
- *DENIED and INTERMITTENT scenarios:* both confirm the same properties across real processes.

**Rejected.**
- *Last-write-wins on a timestamp:* silently destroys an operator's work.
- *Operation-based CRDTs:* assume reliable causal delivery.
- *Manual merge UI:* moves the problem to the operator at the worst moment. A CONFLICT is shown, and a person resolves it by writing a value that supersedes both, but nothing is lost while it waits.

---

### ADR-006 — Bandwidth triage by decision urgency

**Status:** Accepted (2026-09-23). The open question was answered by measurement.

**Decision.** When bandwidth is constrained, sync order is:
1. **class:** summaries, then urgent full records, then routine, then history;
2. **within a class, earliest deadline first:** the deadline is the maneuver commit point;
3. **consequence** as the tie-breaker.

**Rationale.** Every system claims to prioritise; the question is by what. Ordering by how soon someone has to act, and how badly, is an answer that encodes the mission. Earliest-deadline-first is optimal on a single resource when a feasible schedule exists (Liu & Layland, 1973).

**Answer to the open question.** Summaries measure **≤ 256 bytes** each, asserted in `tests/sync`. At about 8 kbit/s, every event was visible as a summary within 5.5 s in the latest run (`docs/ddil-results.md`), with the imaging catalog's element-set summaries sharing the manifest.

Admission control handles the case where the full record can't make it in time. If the link rate measured by the agent cannot deliver a full CDM before its deadline, the event is marked SUMMARY-ONLY rather than spending the link on it. At the bottom of the ladder a summary renders as one voice-readable line.

**Measured.** Same link, same bytes, same 13 CDMs: the most urgent event's full CDM arrives in **12.1 s with EDF vs 46.8 s with FIFO** (3.9×) in the latest run (`docs/ddil-results.md`, generated).

---

### ADR-007 — AI decision support: Jev routes, code computes, Claude phrases, the operator decides

**Status:** Accepted (2026-09-23). Replaces the earlier proposal of a local quantized model as the only AI tier.

**Decision.** The assistant has three parts, and none of them can produce a risk number.

| Part | Job | Hosted provider | Always-available floor |
|---|---|---|---|
| System One: router | Turns the operator's words into one catalogued tool call: which tool, which event, which band or decision | **Jev** (`jev-1.13.0`, pinned). It answers typed Choice questions whose options are exactly the tool catalog and the events on this node, with calibrated probabilities, in one parallel pass | Deterministic rules: slash commands (confidence 1.0) and keywords (0.6) |
| Tools | Compute the facts | none: Sentinel's own services, the code the validation report covers | the same |
| System Two: narrator | Phrases the facts for the operator | **Claude** (`claude-opus-5`, low effort, server-side refusal fallback) | Templates: deterministic, and tested to be grounded on every tool and exercise event |

The guards, each enforced in code and tested:

1. **Tier policy** (`sentinel/ai/policy.py`) is a pure function of the *measured* link state, the classification marking and operator opt-in (`SENTINEL_AI_CLOUD`). Hosted AI needs an UNCLASSIFIED marking and opt-in. Jev may run on CONNECTED, DEGRADED and LIMITED links, because its answer is a few probabilities. Claude runs only on CONNECTED and DEGRADED links, because prose is kilobytes. DENIED means local only. A hosted call gets one attempt with no retries, and any failure (authentication, rate limit, server error, unreachable, timeout, refusal) falls back to the local tier within the same answer. The answer says that it fell back.
2. **Confidence gate.** Below 0.5, or when an event tool has no event, the assistant asks back with the top alternatives instead of acting.
3. **Number-grounding guard.** Every number in an AI-written answer must match, at the precision it is stated, a number in the tool results or in the operator's question. Otherwise the answer is withheld, the template answer is shown instead, and the unsupported numbers are named. Numbers attached to units ("10.9h", "240700Z") are checked too.
4. **Writes are drafts.** A person confirms a draft, and it becomes a signed DECISION carrying its provenance: router, confidence, model and audit sequence. Confirmation is refused if the CDM the draft was made against has been superseded since.
5. **Audit.** Every ask and every confirm is one line of a hash-chained log (`GET /api/ai/audit/verify`).
6. **Enforced in CI, not asserted.** `.importlinter` forbids `sentinel.ai` from importing `risk`, `cdm`, numpy or scipy, so the model has no path to the maths. It also confines the hosted SDKs to their two adapter modules. An air-gapped bundle without the `ai` extra serves the local tier.

**Why Jev as System One.** Routing is classification over a closed set, and Jev's interface is exactly that. It answers declared questions with a probability for every option, and it cannot answer outside them. That gives three properties the assistant needs:
- a calibrated confidence, which makes the ask-back gate principled;
- a small answer, so routing survives a LIMITED link;
- a measurable behaviour, scored by `make ai-eval`.

Its documented weaknesses are arithmetic, dates and prompt injection, and each is designed around:
- time windows are parsed by code, dates are formatted by code, and Jev is never asked for a number;
- object names travel as data;
- the gate and the grounding guard bound what an injected answer can do.

**Why a deterministic floor instead of a local model.** The floor always works and is exact for commands. On natural language it is weak, and the eval says so: `docs/ai-eval.md` measures it routing under half of in-scope requests (0.46) to the right tool. That gap is what a model has to earn its place against, measured on the same set through the same gate. Jev's numbers are published only from a real run. A local model can slot in later behind the same `Router` protocol as a DENIED or classified tier (open question 4). It is not built.

**Assumption, stated.** An edge reaches hosted AI over the same link it uses to reach its hub, so the measured hub-link state stands in for the WAN. A hub or standalone node has no upstream link to measure. It is treated as CONNECTED, and the console labels that as assumed.

**Rejected.**
- A model that computes or "checks" a Pc. There is no path to the maths, by construction.
- Free-form query generation against the store: unbounded and unauditable.
- An LLM tool-calling loop as the router. Its answers are larger, which rules out LIMITED links, it gives no calibrated probability per option, and a request needs only one tool call.
- Retries on hosted calls. The local answer is already there, and backoff on a degraded link only delays the operator.
- Hosted-only AI, which fails principle 1.

---

### ADR-008 — Reference data: application-level priority pull, not transport replication

**Status:** Accepted (2026-09-23).

**Decision.** The edge pulls CDMs from the hub over request/reply. Each cycle:
1. fetch the manifest, skipped if its digest is unchanged;
2. take the set difference against local records;
3. fetch in triage order;
4. re-assess each CDM locally and compare its inputs hash with what the hub asserted.

An event stays HUB-ASSERTED until that comparison passes (VERIFIED), and any disagreement is flagged MISMATCH.

**Why not a JetStream mirror.** A mirror replicates in stream order. That is exactly the FIFO baseline the LIMITED scenario measures at 3.9× slower for the record that matters in the latest run (`docs/ddil-results.md`).

**Why this also buys modularity.** The pull agent reads only generic fields: id, deadline, consequence and record list. It reaches a mission module only through the `ReferenceRecords` protocol, and `.importlinter` forbids `sync` from importing any mission module. The pass module (M3) does: its element sets travel through the same agent, and `sentinel/sync` is unchanged since M2.

**Consequence.** The hub assigns event identity and the identity travels with the record (`Sentinel-Event-Id`). Updates fetched out of order would otherwise split one event into two.

**Reference data on a thin link (measured in M3).** Sync fetches one record per request/reply, and each record also adds a summary to the priority manifest. In a development run, a hub offering all 167 public element sets it holds pushed DEGRADED convergence past its 180 s bound and LIMITED's FIFO baseline past 200 s.

A hub therefore offers edges only what their missions use: the 38-set imaging catalog (`SENTINEL_SYNC_ELEMENTS=catalog`; `all` to widen). It still holds everything for its own screening.

Even that costs something. In the latest run every event summary arrived at 5.5 s, not sooner, because 38 more summaries ride in the manifest, and the urgent record followed. Two sync changes would remove the cost: batched fetch, and a reference-data class below routine CDMs. They are open question 6, not done, so the generated DDIL numbers describe the code as it is.

---

### ADR-009 — Each node serves its own console; node-local events never cross a link

**Status:** Accepted (2026-09-23).

**Decision.** Every node, whether hub or edge, serves its own UI and API from its own data.
- Console events are published on node-scoped subjects (`node.<id>.>`).
- Edge leafnode permissions deny exporting or importing `node.>`.

**Rationale.** A console that depends on the link to another node goes dark exactly when the operator needs it.

NATS leafnodes propagate subject interest. Without node scoping, an edge console subscribed to `cdm.accepted.>` would receive the hub's events before they had been fetched and verified. That would quietly defeat the HUB-ASSERTED/VERIFIED distinction.

---

### Findings from the DDIL harness: NATS defaults assume a LAN

The real-process harness surfaced four defaults that would have failed a satellite-class deployment. Each is now fixed in `deploy/nats/*.tmpl`, and each has a scenario guarding it.

| Default | What happened over the emulated link | Fix |
|---|---|---|
| Leaf listener advertises its URL | After the first disconnect the edge reconnected **directly to the advertised address, bypassing the intended path**. Behind a relay or guard, that is a routing surprise. | `no_advertise: true` |
| Remote first-INFO timeout 1 s | The hub's INFO takes longer than 1 s at 8 kbit/s plus 600 ms, so the leaf reconnected forever. | `first_info_timeout: 20s` |
| Leaf authentication timeout 2 s | The handshake could not complete over the thin link. | `authorization { timeout: 30 }` |
| Ping interval 2 min | A black-holed link took minutes to detect. | `ping_interval: 5s`, `ping_max: 3` |

The RECOVERY scenario (DENIED straight to LIMITED) failed until the second and third fixes were in. It now re-establishes the leaf in 11.8 s.

---

### ADR-010 — OPSEC as architecture: a unit's position never leaves its edge node

**Status:** Accepted (2026-09-24).

**Decision.** A ground unit's position, and every pass window and gap computed from it, exist only on the edge node that serves that unit's operator. Four independent layers enforce this:
1. **Data model.** The unit is not a sync record.
   - Public element sets flow hub to edge through the unchanged priority agent (ADR-008).
   - Nothing implements the record interface for the unit or its passes.
2. **Application.** The only message is the node-scoped `node.<id>.passes.updated`, with no id and no coordinates. The unit is never logged, and error messages never echo a submitted value.
3. **Storage.** One file, `<var>/unit.json`: mode 0600, replaced atomically, never written to SQLite or the audit log.
4. **Transport.** The edge's leafnode denies exporting `unit.>`, `passes.>` and `node.>`. So even an application bug stops at the edge's own nats-server.

**Rationale.** The unit's location is the most sensitive fact in the system, and the hub never needs it: pass prediction runs on public element sets the edge already holds. Computing at the edge removes the flow rather than protecting it. The transport permissions make that enforceable as NIST SP 800-53 AC-4 (information flow enforcement).

**Evidence.** The OPSEC scenario in `docs/ddil-results.md` runs real hub and edge processes and captures every message the hub's nats-server carries. It asserts the following:
- **What the hub never sees:**
  - No message contains the unit's id or coordinates, in any of the text and binary encodings it checks.
  - A canary published on `unit.>`, `passes.>` and `node.>` never reaches the hub.
  - The hub's `/api/passes/unit` is 404.
  - No hub file holds the unit.
- **Controls, so none of those negatives is vacuous:**
  - A harmless canary on an exported subject does reach the hub.
  - The edge does publish its local event.
  - The detector does find the unit in the edge's own file.
- **Element sets did arrive:** they reached the edge through sync.

**Consequences.**
- A cut-off edge keeps computing from the element sets it holds. As they age the timing pad widens, and after three days they are flagged stale.
- The hub has no picture of any unit, by design. An aggregate view would need an explicit, reviewed release path.
- Sharing a unit between edges would need its own decision and a cross-domain guard.

**Rejected.**
- Computing at the hub and sending windows down: that puts the position on the link and on the hub's disk.
- Encrypting the position end to end to the hub: the hub still holds it.
- Leaf permissions alone: they are one configuration line away from a leak.

---

### ADR-011 — Two pass providers behind one contract, held to one conformance suite

**Status:** Accepted (2026-09-24).

**Decision.** The pass module computes overhead windows through a `PassProvider` protocol (`sentinel/passes/model.py`). There are two independent implementations:
- `skyfield-local`: SGP4 from public element sets;
- `tabulated-ephemeris`: interpolation of an Earth-fixed state table from a CCSDS 502.0-B-3 OEM or a source adapter. Wayfinder is one such adapter, on an *assumed* schema; see `docs/adapters/wayfinder.md`.

`tests/conformance/` holds both to the same contract:
- the overlap convention;
- sorted, signed windows;
- a brute-force Skyfield oracle: rise and set within 2 s, maximum elevation within 0.1°.

Adding a provider is one factory and one line.

**Coverage rule.** A provider asked about an imager its data does not cover raises `ImagerNotCovered`. It never skips the imager. Callers pair the catalog with the data first and report what they skipped.

**Rationale.** Two implementations agree only if the contract is what they share, not the code. The conformance suite makes the MOSA claim testable, and it paid for itself on its first run. It found that one provider skipped an uncovered imager with a warning while the other raised. Skipping makes every gap look longer than it is, which is the dangerous direction for an OPSEC product, so the stricter behaviour became the contract.

**Admission.**
- An ephemeris is admitted only in an Earth-fixed frame and UTC.
- Non-increasing epochs, malformed numbers or a step over 300 s raise with a stable code.
- A missing velocity degrades with a recorded warning.
- Tables are never extrapolated.

**Rejected.**
- Converting inertial frames on ingest: it needs Earth-orientation data and adds a silent error source.
- Trusting Skyfield's event finder as-is: the 1 s oracle showed rises up to 0.5 s late, so the local provider now refines rise and set to 1 ms.
- A bespoke ephemeris format: OEM is the standard seam.

---

### ADR-012 — Keyless signing, verified offline against a pinned trust root

**Status:** Accepted (2026-09-24).

**Decision.** Releases are built and signed in GitHub Actions (`.github/workflows/release.yml`):
- cosign keyless signing;
- SLSA build provenance and SBOM attestations;
- every action pinned by commit SHA.

Each air-gap bundle carries its Sigstore bundle. It is verified **before unpacking**, against a Sigstore trust root pinned by sha256 in `deploy/tools.lock`. One gate, `deploy/bundle/verify_signature.sh`, does this with no network for `make airgap-verify` and the Ansible role alike (NIST SI-7, CM-14); the bundle's `install.sh` then checks every file against `SHA256SUMS`. SBOMs are produced in SPDX and CycloneDX. A Trivy gate fails on any finding without a reviewed VEX statement, and every statement's evidence is re-checked on each scan.

**Stated honestly: SLSA Build L2, not L3.** The build is hosted and the provenance is signed. But the provenance is generated inside the repository's own workflow rather than an isolated reusable one.

**Measured locally** (`make airgap-selftest`, `make airgap-local`):
- A tampered bundle is refused before unpacking, even with regenerated checksums. So are an unsigned one, one with the wrong key, and one with the wrong identity.
- An authentic bundle installs inside `unshare -rn` and reproduces the NASA validation offline.
- The single scanner finding is GO-2026-5932, in `nats-server`'s vendored `golang.org/x/crypto/openpgp`. It carries a VEX statement backed by a check that neither binary contains openpgp code.

**Rejected.**
- A long-lived release key: custody and rotation are the risk. Site keys stay supported for enclave countersignature.
- Verifying online at install time: that fails the premise of an air gap.
- "Empty but valid" VEX: the OpenVEX schema requires at least one statement, so with no findings the document is simply omitted.

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
         │                │          NATS (local)            │
         │                └──────────────────────────────────┘
         │                       │              │           │
         ▼                       ▼              ▼           ▼
  ┌──────────────┐        ┌───────────┐  ┌───────────┐ ┌──────────┐
  │ Store &      │        │ Triage /  │  │ Decision  │ │ AI query │
  │ forward queue│        │ ranking   │  │ log (CRDT)│ │ (ADR-007)│
  └──────────────┘        └───────────┘  └───────────┘ └──────────┘
         │                                      │
         └──────────── SYNC LAYER ──────────────┘
                   (priority by ADR-006)
```

As built, the CelesTrak path runs through demonstration mode (ADR-002), the Wayfinder adapter produces ephemerides for the pass module rather than CDMs (ADR-011), and there is no Space-Track adapter yet. Priority pull (ADR-008) and CRDT anti-entropy (ADR-005) take the place of a store-and-forward queue.

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

**Risk engine.** Unit tested against NASA CARA's published test cases, closed forms, and an independent `scipy.integrate.dblquad` oracle (Orekit was dropped; ADR-003). Dilution-region detection tested against constructed cases where inflating covariance lowers Pc — demonstrating the flag fires on exactly the pathology it exists to catch.

**DDIL behavior.** A reproducible harness (`harness/`): real `nats-server` processes, with Toxiproxy shaping the leafnode TCP link. Named scenarios run as CI jobs (`.github/workflows/harness.yml`) rather than manual demonstrations:

- *Denied* — total isolation (20 s per run, 15 minutes nightly), then reconnect. Assert no data loss, correct merge, priority-ordered catch-up.
- *Degraded* — high, jittery latency and a bandwidth cap. Assert continued operation and convergence.
- *Intermittent* — repeated short drops. Assert no duplicate decision log entries.
- *Limited* — hard bandwidth cap at satellite-link rates. Assert priority ordering holds and degraded summaries transit.
- *Recovery* — DENIED straight to LIMITED. Assert the leaf re-establishes and operator data written while denied reaches the hub.
- *OPSEC* — see ADR-010.

The recorded results of the latest run are generated into `docs/ddil-results.md`.

**AI layer.** Three kinds of evidence:
- Unit tests pin every guard: the tier policy, the confidence gate, grounding, confirm-once and stale drafts, and audit-chain tampering.
- The Jev and Claude adapters run their real SDKs against mock transports, which pins the wire requests without a network or a key.
- `make ai-eval` scores the routers on 60 labelled requests, reporting accuracy, coverage, abstention, Brier score, ECE and a reliability diagram. The report (`docs/ai-eval.md`) is generated and never hand-edited.

---

## 7. Open Questions

1. Does Space-Track CDM-class access get granted? Gates demonstration versus assessment mode as the default.
2. ~~Orekit-python CI viability (ADR-003).~~ Answered: Orekit was dropped as the oracle, because CARA's published results are a stronger reference.
3. ~~Degraded-summary sizing against a realistic link budget (ADR-006).~~ Answered by measurement; see ADR-006.
4. Whether a local model beats the deterministic floor by enough to justify its footprint at the edge (ADR-007). To be measured with `make ai-eval`, not assumed.
5. Whether the TraCSS transition changes CDM access mechanics during the build window.
6. Batched fetch or a reference-data priority class in sync, so public reference data stops competing with urgent CDMs on a thin link (ADR-008). It would be the first change to `sentinel/sync` since M2, made deliberately and measured.

---

## 8. Document Trail

| Artifact | Derives from | Audience |
|---|---|---|
| This design (`docs/system-design.md`, with the maths in `docs/risk-engine-design.md`) | NASA CARA's published methods and data, CCSDS standards | Self, technical reviewers |
| Technical guide | This design | Engineers reading the repo |
| White paper | Technical guide | Acquisition, operational, executive |
| SysML v2 model (`mbse/`) | This design | MBSE demonstration; `docs/traceability.md` is generated from it in CI |
| OSCAL draft SSP (`compliance/oscal/`, explained in `docs/compliance.md`) | Implementation and CI evidence | Security/ATO reviewers |

Written once, derived three times. The white paper is not a separate research effort; it is this document retargeted at a reader who cares about mission outcome and risk rather than about NATS.
