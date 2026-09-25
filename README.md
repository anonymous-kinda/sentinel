# Sentinel

A demonstrator of a collision-risk decision aid for satellite operators. It is honest about what its numbers can support, and it keeps working when the network does not.

Sentinel is built and measured end to end on exercise and public data. It proves an architecture with measured numbers. It is not an operational capability: nothing is fielded, and no authority to operate is claimed. Its [limits](#limits) follow straight after its value.

![Sentinel operator console](docs/img/console.png)

---

## What it gives an operator

A satellite operator receives warnings that a tracked object may pass close to one of their spacecraft. Before the maneuver commit point, they must decide whether to spend propellant avoiding it. Sentinel is a decision aid for that call.

| Value to the operator | Evidence |
|---|---|
| **No false reassurance.** A low probability of collision (Pc) can mean "we barely know where either object is". Sentinel detects that dilution and says so. It refuses rather than print a number its model does not support. | Sentinel's Pc matches NASA CARA's published value on 53 real operational conjunctions (worst relative error 1.5e-8), and it refuses all 29 events where CARA says the method does not apply. [Validation report](docs/validation-report.md). |
| **The most urgent data crosses a thin link first.** | At about 8 kbit/s, the most urgent full CDM arrived in 9.1 s in deadline order, against 136.9 s in arrival order. Both orders moved the whole backlog in about the same time (150.9 s and 149.0 s), so putting the urgent record first costs almost nothing. Medians of 5 runs per mode. [DDIL results: LIMITED](docs/ddil-results.md#limited). |
| **It keeps working disconnected.** Decisions made offline merge without loss. Conflicting edits are shown, not silently overwritten. The edge re-computes the hub's numbers rather than trusting them: an event is VERIFIED only when the edge's own result matches the hub's, field by field. | Cut off, the edge console answered at 3.2 ms (95th percentile) and all 11 DENIED checks passed. On reconnect, operator data converged in 1.37 s. [DDIL results: DENIED](docs/ddil-results.md#denied) and [RECOVERY](docs/ddil-results.md#recovery); ADR-005 and ADR-008 in the [system design](docs/system-design.md). |
| **It is built for the approval path.** In DoD, getting approval to operate often takes longer than building the software. Sentinel produces the evidence an assessor asks for as it is built. | Signed releases, verified offline before anything is unpacked; SBOMs and VEX; a requirement trace and an OSCAL security package generated from test evidence. [Supply chain](docs/supply-chain.md), [compliance](docs/compliance.md). |
| **A ground unit learns when public imagers can see it,** and its position never leaves the unit's own node. | On a real hub and edge, the hub's server carried 179 messages while the edge computed a unit's passes. None held the unit's id or coordinates, and all 10 OPSEC checks passed. [DDIL results: OPSEC](docs/ddil-results.md#opsec); ADR-010. |

The AI assistant is not on this list, on purpose. It is a safety pattern rather than a headline capability: [how to put AI into a disconnected or classified system without letting it corrupt a decision](#ai-that-cannot-corrupt-the-decision).

---

## Limits

Sentinel is a demonstrator. What it shows is an architecture, measured. It does not show an operational capability.

- **Exercise and public data only.** The inputs are NASA CARA's published CDMs, a scripted exercise scenario labelled EXERCISE, and a public CelesTrak element-set snapshot. No live CDM feed is connected.
- **Nothing is fielded.** No operator has used Sentinel on a real mission. The DDIL numbers come from real processes on one machine, with the link shaped by Toxiproxy. They are not measurements of a tactical or satellite link.
- **No ATO is claimed.** The OSCAL package is a draft system security plan, with assessment results and a plan of action and milestones generated from tests. No authorizing official has reviewed it.
- **Open security gaps.** Each is a real weakness in the current code, tracked in [`SECURITY.md`](SECURITY.md):
  1. operators are not authenticated: the node trusts a proxy header for the operator's name (IA-2);
  2. the hub-to-edge link has no TLS (SC-8);
  3. removing the newest AI-audit lines while the node is stopped goes undetected (AU-9);
  4. annotations (triage status, assignee, note) are not signed, so a peer that can reach the hub can erase one. The decision log is signed.
- **Not yet run for real.** No release has been signed on a tag, and CI has not run on a hosted service. The containers have not run: the `compose-smoke` CI job will be their first run. No hosted AI model has been measured.
- **2D only.** Events that need a 3D assessment are refused, not answered ([below](#no-false-reassurance-the-risk-engine)).

---

## No false reassurance: the risk engine

**A low probability of collision is not by itself evidence of safety.**

Collision probability is computed by integrating position uncertainty over
the combined hard-body radius. Past a certain point, *more* uncertainty
produces a *lower* probability - the mass gets smeared thin and less of it
lands on the disk. So a reassuring number can mean either "we know precisely
that these will miss" or "we barely know where either object is."

Sentinel computes where the operating point sits relative to that peak and
says so. Run `uv run python scripts/dilution_demo.py` (set up as in [Reproduce the evidence](#reproduce-the-evidence)):

```
 sigma (m)            Pc        Pc max        k*                 verdict
------------------------------------------------------------------------
       100     9.656e-27     3.679e-07    50.000           bounded above
       300     2.148e-08^    3.679e-07     5.556           bounded above
       500     2.707e-07^    3.679e-07     2.000           bounded above
       646     3.614e-07^    3.679e-07     1.200           bounded above
       707     3.679e-07^    3.679e-07     1.000           bounded above
     1,000     3.033e-07v    3.679e-07     0.500  DILUTED - Pc unreliable
     2,041     1.065e-07v    3.679e-07     0.120  DILUTED - Pc unreliable
     5,000     1.960e-08v    3.679e-07     0.020  DILUTED - Pc unreliable
```

Geometry is identical on every row. Only the quality of the orbit solution
changes. The first row and the last row both report a probability below
1e-7; one is a precise measurement and the other is near-total ignorance.

The boundary has a closed form: dilution begins once the 1-sigma uncertainty
exceeds the miss distance over root two.

**No number where the model does not apply.** Sentinel refuses, with a named reason and the value that tripped the check, rather than print a number that looks authoritative:

- **No Pc without covariance.** Element sets alone do not support a Pc. NASA CARA's position is that two-line elements are not sufficient for conjunction assessment: kilometre-scale theory error is too large for maneuver planning, and no covariance is available to compute a probability from. Screening on element sets and printing a Pc anyway is the most common way to get this wrong.
- **No Pc at low relative speed.** Low relative velocity breaks the straight-line encounter assumption: the geostationary and similar-orbit case. The console says the event needs a 3D assessment. Building the 3D method that would answer those cases is deferred; detecting that it is needed is not.
- **No Pc where NASA's own reference says the 2D method is wrong.** CARA publishes 53 real operational conjunctions with its verdict on whether the 2D method applies. Sentinel's gate refuses **every one** of the 29 that CARA flags. On those events CARA's 3D result differs from the 2D value by up to 60,722× at orbital speeds, and by up to 162 orders of magnitude at low relative velocity. The threshold was calibrated on that same set, and the validation report states this next to the result.

A refusal is shown as a refusal, never as a zero.

**What Sentinel does with element sets instead is *demonstration mode*.**
`sentinel screen --primary 40115 --hours 24` screens a satellite against the
bundled public CelesTrak snapshot and lists every close approach: object,
time of closest approach, miss distance and relative speed. Every line says
*Pc: refused — element sets have no covariance*. The bundled snapshot is one
small public group, so a 24-hour window at the default 5 km threshold is
often empty ("no close approaches"); widen it with `--threshold-km 50` to see
the listing. With `--out DIR` it writes each approach as a DERIVED CCSDS CDM.
Fed back in, the risk engine refuses it with `NO_COVARIANCE`, the same gate
any covariance-less CDM meets. There is no special case in the engine
(ADR-002).

### Validation

`docs/validation-report.md` is generated from two kinds of expected value: closed forms, and numbers NASA CARA published. None comes from running this code.

| check | reference | result |
|---|---|---|
| 53 real operational conjunctions (HST, TERRA, SWIFT, ...) | CARA's published Pc2D | worst relative error **1.5e-8** |
| Gate vs CARA's "2D invalid" verdicts | CARA's `ViolationsPc2D` | **29/29 refused, 0 missed**, 5 conservative refusals |
| Alfano (2009) benchmark, read from CDM files | CARA unit test | all within CARA's rtol 1e-3 |
| Omitron Case 1 | CARA `PcCircle` high-accuracy | 1.9e-8 |
| Omitron Case 2 | CARA `PcCircle` | difference explained to 1e-14 by miss-distance convention |
| Isotropic zero-miss integral | `1 - exp(-R²/2σ²)` | 2.2e-12 |
| Pc-maximising scale factor | `k* = (d²/2)/σ²` | 5.2e-07 |
| Maximum Pc | `Pc_max = R²/(e·d²)` | 4.2e-14 |

The NASA files are vendored **unmodified** under `fixtures/cara/`, with NOSA 1.3 agreements, provenance and SHA-256 checksums verified by the test suite. The quadrature is also cross-checked against `scipy.integrate.dblquad` in Cartesian coordinates (a different algorithm over a different parameterisation) at `rtol=1e-8`.

---

## The operator console

`make serve`, then open http://127.0.0.1:8000. One process serves the API and the console.

- **Operations.** Active conjunctions sorted by time to the maneuver commit point, which is when a decision is due, not when a message arrived. A scripted exercise scenario plays out live: CDM updates arrive on schedule and the list re-ranks as they do.
- **The two plots that carry the argument.** The encounter-plane view and the Pc-vs-covariance-scale curve share one slider. Drag it and the uncertainty ellipse grows past the hard-body disk while Pc climbs, peaks, then *falls*. That is dilution, shown rather than described.
- **Refusals are first-class.** A refused event shows why, the value that tripped the gate, and the threshold. It is never shown as a zero.
- **Provenance on every number.** Inputs hash, engine version, source CDM hash, and the originator's own Pc labelled as theirs.
- **NASA reference.** The 53 CARA operational events, ingested through the same parser.
- **Validation.** The node re-runs the NASA comparison with the engine it is actually running and shows the agreement.

The globe is CesiumJS using imagery bundled with the application, with no ion token, geocoder or CDN. The node serves the console under a `default-src 'self'` Content-Security-Policy (asserted in `tests/api/test_api.py`), so the browser itself blocks any request beyond the node. The console works on a network with no route to the internet, or it is not a field tool.

![Validation tab](docs/img/validation.png)

---

## Urgent data first, and a node that keeps working cut off

Conjunction assessment tooling is mostly hosted. An operator on a deployed ground station, a ship, or any denied or degraded link loses the decision aid exactly when the decision is due, and the commit point does not move because the network went down.

Each Sentinel node runs its own `nats-server` and serves its own console. The edge's server holds a leafnode link to the hub. In the harness, [Toxiproxy](https://github.com/Shopify/toxiproxy) shapes that real TCP link: black-hole (DENIED), 600 ms / 32 kB/s (DEGRADED), about 8 kbit/s (LIMITED), and repeated drops (INTERMITTENT).

```bash
make demo-local      # hub :8000, edge :8001 - the edge's LINK chip shapes the real link
make compose-up      # the same hub and edge in containers; only Docker needed (docs/compose.md)
make ddil            # every scenario on real processes -> docs/ddil-results.md
```

**Denied: the edge keeps working.** The console stays up (3.2 ms p95 while cut off). Operators triage events and record signed decisions locally, and the link state is *measured*, not configured.

![Edge node while the link is denied](docs/img/edge-denied.png)

**Limited: what matters crosses first.** The edge gets a summary of every event (at most 256 bytes each) first: within 6.5 s, the median of 5 runs. Then full CDMs follow, earliest maneuver commit point first. The edge re-assesses each one and compares its result with what the hub asserted: the inputs hash, method, band, worst-case band, Pc, worst-case Pc, dilution flag, miss distance and relative speed. An event is HUB-ASSERTED until then, VERIFIED once every field matches, and MISMATCH if any does not.

On the same link with the same bytes, the most urgent full record arrives in **9.1 s with earliest-deadline-first vs 136.9 s in FIFO order** (15.0×, medians of 5 runs per mode; every run is listed in `docs/ddil-results.md`). Each run starts from the same backlog at the hub: the exercise CDMs and the 38 imaging-catalog element sets that the hub's default configuration offers edges. The leaf connects over the already-shaped link, and the scenario checks each run's link and the records it moved. The order decides which record arrives first, not how long the backlog takes. ADR-006 explains why the comparison runs this way, and ADR-008 records what reference data costs on a thin link.

![Sync tab over a limited link](docs/img/edge-sync.png)

**Reconnect: nothing lost, nothing overwritten.** Operator data is a CRDT (property-tested under drop, duplication and reordering):
- the hub and the edge converge to the same state;
- two people who changed the same event's triage status while partitioned see a **CONFLICT** that names both, instead of whoever-wrote-last winning;
- a decision made offline against a CDM that has since been superseded is flagged **REVIEW REQUIRED**.

![Conflict and review-required after reconnect](docs/img/edge-conflict.png)

The harness also found four NATS defaults that assume a LAN. One would have made a satellite-linked edge reconnect forever, and another let the edge silently route around its intended path. They are fixed and each is guarded by a scenario (`docs/system-design.md`, "Findings from the DDIL harness").

**In containers.** `make compose-up` runs the same topology with only Docker needed, and `make compose-link PRESET=DENIED` shapes the link. `make compose-smoke` checks that the edge syncs and verifies the hub's events, keeps answering while DENIED, reconverges, and never lets a unit reach the hub. It has passed against the process harness; the containers themselves have not run yet (`docs/compose.md`).

---

## Overhead passes for a disconnected Army unit

A unit on the ground needs to know when a catalogued imaging satellite can see it, and when none can for long enough to move. Answering that usually means sending the unit's position somewhere central, which is the one fact the unit most needs to protect. Sentinel answers it at the unit's own edge node instead.

- **What it computes.** Pass windows for 38 public-catalog EO and SAR imagers, from public CelesTrak element sets and each imager's field of regard. Fields of regard are planning assumptions with cited sources, chosen to err wide. EO passes count only when the unit is lit. The next window long enough for the unit's reaction time is shown as a date-time group.
- **What it will not say.** A gap is labelled *not observed by catalogued imagers*, never "safe": uncatalogued and non-public sensors are outside the model, and a test keeps the word out of the module and the console. Element-set error is covered by a timing pad that widens with age, and sets older than three days are flagged stale.
- **The unit's position never leaves the edge (ADR-010).** It is not a sync record, never logged, stored in one 0600 file, and the edge's leaf link denies the subjects that could carry it. The OPSEC harness scenario checks this on real processes: the hub's wire never carries the unit in any checked encoding, and a deliberate canary never crosses. The results are in `docs/ddil-results.md`.
- **Two providers, one contract.** Local SGP4 and a CCSDS OEM ephemeris provider must both pass one conformance suite: rise and set within 2 s of a brute-force oracle. A Wayfinder adapter feeds the second provider, on an *assumed* schema (see `docs/adapters/wayfinder.md`) (ADR-011).
- **Reference data rides the same sync.** Public element sets reach the edge through the unchanged priority agent. The hub offers edges only the imaging catalog, and ADR-008 records what that costs on a thin link.

![Passes tab: next unobserved window, the unit, and 24 h of pass windows by imager](docs/img/passes.png)

---

## Built for the approval path

A classified or disconnected site has to trust a bundle without reaching the internet to check it, and an assessor has to see which requirement each piece of evidence proves.

- **Signing.** Releases are signed keyless with Sigstore from GitHub Actions. They carry SLSA **Build L2** provenance and SPDX SBOM attestations; SPDX and CycloneDX SBOMs ship alongside, covered by the signed checksum list. Build L2 is the honest level; `docs/supply-chain.md` explains why this is not L3. No release has been signed on a tag yet.
- **Offline verification.** Every install path verifies the signature against a pinned Sigstore trust root (or a site key) before unpacking anything, with no network. `make airgap-verify` and the Ansible role run the same gate, `deploy/bundle/verify_signature.sh`; the bundle's `install.sh` then checks every file against its `SHA256SUMS`.
- **Local proofs.**
  - `make airgap-selftest` shows that a tampered, unsigned, wrong-key or wrong-identity bundle is refused.
  - `make airgap-local` builds a bundle, signs it with a throwaway key, and installs it inside a network namespace with only loopback. There it reproduces the NASA validation and, as a hub, loads its bundled element sets. The `airgap-install` CI job is configured to repeat this for each architecture.
- **Vulnerability gate.** Scans fail on any finding without a reviewed VEX statement. The one current finding (GO-2026-5932, against the `openpgp` package of a Go module `nats-server` depends on) is shown not to be linked into the binary, and that check re-runs on every scan.
- **Security package.** `make compliance` turns a test run's evidence into OSCAL assessment results and a plan of action and milestones, beside a draft system security plan. Every control not fully implemented is a POA&M item (`docs/compliance.md`). No ATO is claimed.
- **Traceability, generated.** `mbse/` is a SysML v2 textual model of Sentinel: requirements, parts, ports, and the link-state and AI-tier state machines. Every requirement traces to the part that satisfies it and the evidence that verifies it: a test, a harness scenario, an import contract or a CI step. CI regenerates `docs/traceability.md` and fails on any reference to evidence that does not exist. Work not built yet is marked *planned* and reported as unverified, never as verified. The current trace has 54 requirements: 54 verified, 0 unverified, 0 broken references. A real SysML v2 grammar (sysml2py, the pilot implementation's grammar) parses the model in CI. That check covers syntax, not semantics.

---

## AI that cannot corrupt the decision

A language model is good at understanding what an operator is asking and at phrasing an answer, and unreliable at arithmetic. A decision aid that lets a model state a collision probability has put an unauditable number in front of someone deciding whether to burn propellant. Sentinel shows one way to put AI into a disconnected or classified system without that risk: **AI routes, code computes, AI phrases, the operator decides.**

| Step | Hosted, when policy allows | With no keys, no link, or a classified marking |
|---|---|---|
| **Route** the request to one catalogued tool | [Jev](https://docs.typesafe.ai) (TypeSafe's System One model), answering typed questions whose options are exactly the tool catalog and the events on this node | slash commands and keyword rules |
| **Compute** the facts | Sentinel's own validated code, never a model | the same |
| **Phrase** the facts | Claude | deterministic templates |
| **Decide** | the operator, who confirms a draft before anything is recorded | the same |

- **It works with no keys.** Local rules and templates answer with no network. The air-gap bundle carries no hosted AI libraries.
- **The tier follows the measured link and the marking.**
  - Hosted AI needs an UNCLASSIFIED marking and operator opt-in.
  - Jev may run on a LIMITED link, because its answer is a few probabilities, not prose.
  - Claude needs CONNECTED or DEGRADED.
  - DENIED means local only.
  - A failing hosted call falls back within the same answer, and the answer says so.
- **No path to the maths.** `.importlinter` forbids `sentinel/ai` from importing the risk engine, the CDM codec, numpy or scipy, so the rule is enforced rather than promised.
- **Any unsupported number is withheld.** An AI-written answer that states a number the tool results do not contain is withheld. The template answer is shown instead, with the offending number named.
- **Unsure means ask.** Below 0.5 confidence, or with no event named, the assistant offers the top alternatives as one-click choices.
- **Drafts, not actions.** "Draft a maneuver decision for 118" produces a draft. A person confirms it, and it becomes a signed DECISION carrying its provenance (router, confidence, model). A draft made against a CDM that has since been superseded cannot be confirmed.
- **Audited.** Every ask and confirm is a line in a hash-chained log that the console verifies.

![Assistant tab: tier, grounding, ask-back and a draft awaiting confirmation](docs/img/assistant.png)

**What is measured, and what is not.** `make ai-eval` scores the routers on 60 labelled requests through the assistant's own confidence gate, reporting accuracy, coverage, abstention, Brier score, ECE and a reliability diagram (`docs/ai-eval.md`). The deterministic floor routes under half of in-scope requests (0.46) to the right tool. No hosted model has been scored: no Jev or Claude number exists in this repository, so no benefit from hosted AI is claimed. Jev's column is filled only by a real run with `TYPESAFE_API_KEY` set.

```bash
SENTINEL_AI_CLOUD=1 TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=... make serve   # hosted tiers (opt-in)
make ai-eval                                                               # score the routers
```

---

## Reproduce the evidence

```bash
uv sync --locked --python 3.12 --extra dev   # exactly uv.lock, as CI does
uv run pytest -q                      # the full suite, network disabled, 0 skipped
uv run pytest -q -m tier3             # NASA CARA published cases
uv run sentinel assess fixtures/cara/PcTestCaseCDMs/000025994_conj_000037558_20210324_151047_20210323_154356.cdm
uv run python scripts/dilution_demo.py      # the dilution table above
make report                                 # regenerate docs/validation-report.md
make ddil                                   # regenerate docs/ddil-results.md on real processes
make ai-eval                                # score the assistant's routers -> docs/ai-eval.md
make trace                                  # regenerate docs/traceability.md
```

The `assess` example is TERRA against a fragment of Iridium 33, a real 2021 event. Sentinel reproduces the originator's Pc of 2.1e-2 and flags it **diluted**: the covariance sits past the Pc peak, and the worst case over covariance scaling is 3.5e-2.

---

## Documents, by reader

[`docs/index.md`](docs/index.md) lists every document and who it is for.

- **Operators and program offices:**
  - the [white paper](docs/white-paper.md);
  - the [quad chart](docs/quad-chart.md);
  - the [3-minute demo script](docs/demo-script.md);
  - the [disconnected-site install guide](docs/install-guide.md).
- **Engineers:** the [technical guide](docs/technical-guide.md) covers architecture, where each module lives, data flows, the configuration reference, the test ladder and how to extend. The [system design](docs/system-design.md) holds the architecture decisions: each opens with what it buys and what it costs, and records the alternatives it rejected. [`docs/icd/`](docs/icd/README.md) has the OpenAPI, AsyncAPI 3.0, CDM admission profile and sync envelope, each held to the code by `tests/docs/`. [`CONTRIBUTING.md`](CONTRIBUTING.md) has the rules and checks.
- **Security assessors:** [`SECURITY.md`](SECURITY.md) (how to report, and the known open gaps), [`docs/supply-chain.md`](docs/supply-chain.md), [`docs/compliance.md`](docs/compliance.md).
