# Sentinel: collision-risk decisions that hold up when the link does not

*Capability white paper for program offices, S6/G6 staffs and space operations units.*

> **Read this first.** Sentinel is an open-source demonstration. It is not fielded, not accredited and not endorsed by any government organization, and no operator has used it on a real mission. Every number in the proof points below comes from a report the repository generates, and each one links to that report. Section 6 lists what fielding would still take.

## Summary

A satellite operator gets warnings that a tracked object may pass close to one of their spacecraft. They must decide, before the maneuver commit point, whether to spend propellant to avoid it. Two things go wrong in practice. The probability of collision can look reassuring for the wrong reason. And the tools that compute it assume a network that a deployed unit will not always have.

Sentinel is a decision aid built for that call. What it gives an operator:

- **No false reassurance.** It computes collision risk with NASA's published method and checks itself against NASA's published results. It flags a probability made low by poor tracking, and it refuses to show a number the method cannot support.
- **The most urgent data first.** When the link is thin, the record due soonest crosses first, and the backlog as a whole takes about as long as it would in arrival order.
- **Work that survives a cut link.** Each node keeps working when its link is cut. Decisions made offline merge without loss, and the edge re-computes the hub's numbers rather than trusting them.
- **Built for the approval path.** In DoD, getting approval to operate often takes longer than building the software. A disconnected site can prove the software is authentic before it installs anything, and the evidence an assessor asks for is generated as the software is built.
- **Pass warnings without giving away the unit's position.** A second module tells a ground unit when public imaging satellites can see it, without the unit's position leaving its own node.

It also shows how to put AI into a classified or disconnected system without letting it corrupt a decision. AI routes the question and phrases the answer, validated code computes, and the operator decides. It works with no keys and no network. No benefit from hosted AI is claimed, because none has been measured.

**Limits.** Sentinel is a demonstrator: it proves an architecture with measured numbers, not an operational capability. It runs on exercise and public data only. It is not fielded, and no authority to operate is claimed. Section 5 lists the open risks, including the security gaps, and section 6 what fielding would take.

## Win themes

- **W1. Numbers you can defend.** Sentinel matches NASA's published results and refuses, with a stated reason, any probability the method cannot support.
- **W2. Works when the link does not.** A cut-off node keeps working; on a thin link, the decision due soonest crosses first.
- **W3. Trusted without a network.** A disconnected site verifies the signature offline, against a pinned trust root, before anything is unpacked.
- **W4. The unit's position stays at the edge.** Pass windows are computed where the unit is; nothing on the hub's wire or disk holds its position.
- **W5. Open seams, traced evidence.** Standard formats at every seam, and a requirement trace that fails on any missing evidence.
- **W6. AI that cannot corrupt a decision.** AI routes and phrases, validated code computes, a person decides, and it works with no keys.

## 1. The operational problem

**The decision.** Warnings arrive as Conjunction Data Messages (CDMs), in the international CCSDS format. Each event arrives as a series of messages, reissued as tracking improves. The operator has until the maneuver commit point to decide whether to maneuver. That deadline does not move because the network went down.

**The number can mislead.** Probability of collision (Pc) comes from how uncertain both objects' positions are. Past a certain point, *more* uncertainty gives a *lower* Pc: the probability is smeared so thin that little of it lands on the objects. This is called dilution. A low Pc can mean "we know these objects will miss" or "we barely know where they are". Those are opposite situations that print similar numbers. Public element sets (TLEs and their successors) carry no uncertainty at all, so they cannot support a Pc, and NASA says so.

**The network is not guaranteed.** Conjunction assessment tools are mostly hosted services. A ground station at a deployed site, a ship, or any denied or degraded link loses the tool exactly when the decision is due. When the link returns, the backlog usually crosses in arrival order, so the urgent record waits behind routine traffic. Two operators who changed the same event while apart often find that one change was silently overwritten.

**AI adds a new way to be wrong.** A language model is good at understanding a question and phrasing an answer. It is unreliable at arithmetic. An assistant that lets a model state a collision probability has put an unauditable number in front of the person who decides whether to burn propellant.

**Ground units have a related question.** A unit wants to know when it can be seen from orbit. Answering that usually means sending the unit's position somewhere central, which is the one fact the unit most needs to protect.

## 2. The approach

**One bundle, three roles.** The same signed bundle installs a cloud hub, a forward edge node or a standalone node. The role is configuration, not a separate build. Every node serves its own console from its own data. The console makes no request beyond its own node, so it works on a network with no route to the internet.

**Honest risk numbers.** Each node reads CDMs in the CCSDS standard format and computes Pc with the Foster-Estes method, ported from the software NASA's Conjunction Assessment Risk Analysis (CARA) team publishes. It also computes the worst-case Pc over all uncertainty scalings and flags dilution. Where the method does not apply, it refuses with a named reason and the value that tripped the check: missing or invalid uncertainty, low relative speed, or uncertainty that bends with the orbit. A refusal is shown as a refusal, never as zero.

**Disconnected, degraded, intermittent, limited.** Nodes connect over NATS leaf links. Reference data (CDMs) is pulled by the edge in mission priority: a small summary of every event first, then full records by earliest maneuver deadline. The edge re-assesses each record itself and compares its answer with the hub's. Operator data (triage, notes, decisions) uses state-based replicated data types: nothing is lost, and concurrent edits are shown as a CONFLICT instead of one silently winning. Decisions are signed per node and hash-chained. A decision made offline against data that has since changed is flagged REVIEW REQUIRED.

**AI as a safety pattern.** The assistant shows how to put AI into a classified or disconnected system without letting it corrupt a decision. It turns an operator's words into one call to a catalogued tool. Sentinel's own validated code computes the facts, and the assistant phrases them. Local rules and templates always work, with no keys and no network. Hosted models (a routing model and a language model) are optional. They are used only with an UNCLASSIFIED marking, operator opt-in and a usable measured link. Any number in an AI-written answer must match the tool output, or the answer is withheld. The assistant only drafts; a person confirms before anything is recorded. No hosted model has been measured yet, so this paper claims the pattern, not a benefit.

**Overhead passes for a ground unit.** The pass module shows when catalogued public imaging satellites can observe a unit, and the gaps between. A gap is labelled "not observed by catalogued imagers", never "safe". The edge computes everything from public element sets its hub sends it. The unit's position is not a sync record, is never logged, and the edge's link permissions refuse to carry it (ADR-010 in the [system design](system-design.md)).

**A supply chain a disconnected site can check.** The release workflow signs bundles without a long-lived key and attaches build provenance and software bills of materials. It has been checked statically; no release has been signed yet. Provenance is claimed at SLSA Build L2, not L3, and the [supply-chain page](supply-chain.md) says why. Every install path verifies the signature against a pinned trust root with no network, before unpacking. A vulnerability gate fails on any finding that has no reviewed exception.

**Evidence as code.** A SysML v2 model holds the requirements. The requirement-to-evidence trace is generated from it, and generation fails on any reference to evidence that does not exist. A security package in OSCAL (a draft system security plan, assessment results and a plan of action and milestones) is generated from each test run. The CI pipeline is configured to run all of this on every change, but the repository has not yet run on a hosted CI service; each step has been run locally.

## 3. Discriminators

What alternatives commonly get wrong, and what Sentinel does instead.

| What alternatives commonly do | What Sentinel does | Why it matters to the operator |
|---|---|---|
| Print a Pc for any pair of objects, including pairs screened from element sets with no uncertainty data | Refuses a Pc without uncertainty data. Element-set screening gives geometry only, and says so on every line | A number that cannot be defended is never shown |
| Treat a low Pc as good news | Shows where the event sits relative to the Pc peak, flags dilution, and shows the worst case | A low number caused by poor tracking is not mistaken for safety |
| Apply the 2D method to every event | Refuses where NASA's own verdict says the 2D method is invalid, with the reason | The operator sees "no valid number", not a wrong one |
| Run as a hosted service that goes dark with the link | Runs each node on its own data; the console keeps working while cut off | The decision aid is there when the decision is due |
| Replicate in arrival order | Sends summaries first, then full records by earliest maneuver deadline | The urgent record is not stuck behind routine traffic |
| Merge on last-writer-wins | Keeps concurrent edits and shows a CONFLICT; flags stale offline decisions | No operator's work disappears without anyone knowing |
| Let a model answer with numbers | Gives the AI no code path to the maths and withholds any answer with an unsupported number | Every number on the screen came from validated code |
| Compute exposure centrally from the unit's reported position | Computes at the edge from public data; the position never crosses the link | The most sensitive fact in the system never leaves the unit |
| Verify an install online, or not at all | Verifies offline against a pinned trust root, before unpacking | A disconnected site can check authenticity itself |
| Write compliance documents by hand | Generates the trace and the security package from test evidence; unbuilt work shows as planned | Reviewers see what is proven and what is not |

## 4. Proof points

Each proof point names its theme and links its evidence. Numbers come only from the generated reports: the [validation report](validation-report.md), the [DDIL results](ddil-results.md), the [AI routing eval](ai-eval.md) and the [requirements trace](traceability.md). The DDIL numbers are one recorded run of real processes on one machine, with the link shaped by Toxiproxy; they are not measurements of a fielded link.

| Theme | Proof point | Evidence |
|---|---|---|
| W1 | On 53 real operational conjunctions that NASA CARA published, Sentinel's Pc matches CARA's value with a worst relative error of 1.5e-08. | [Validation report](validation-report.md#5-nasa-cara-53-real-operational-conjunctions); `tests/test_tier3_cara_validation.py::test_pc2d_matches_published_cara_value` |
| W1 | CARA flags 29 of those 53 events as outside the 2D method. Sentinel refuses all 29 and returns a Pc for none of them. It also refuses 5 events CARA would compute. The threshold was set on this same set of events, and the report says so. | [Validation report](validation-report.md#6-the-applicability-gate-against-caras-own-verdicts); `tests/test_tier3_cara_validation.py::test_gate_refuses_every_event_cara_says_2d_cannot_handle` |
| W1 | On the refused events above 100 m/s, CARA's own 3D result differs from the 2D value by factors of 0.016 to 60,722. Those are the numbers the refusals keep off the screen. | [Validation report](validation-report.md#6-the-applicability-gate-against-caras-own-verdicts) |
| W1 | The worst-case Pc matches its closed form to a relative error of 4.17e-14, and inflating the uncertainty by an order of magnitude lowers Pc and sets the dilution flag. | [Validation report](validation-report.md#3-maximum-probability-of-collision); `tests/test_tier4_dilution.py::test_inflating_covariance_by_one_order_of_magnitude_lowers_pc_and_sets_flag` |
| W1 | Element-set screening lists each close approach and states that the Pc is refused. Each approach is filed as a DERIVED CDM, and the engine refuses it for missing uncertainty data. | `tests/screening/test_cli_screen.py::test_each_approach_is_listed_with_its_pc_refused_and_written_as_a_derived_cdm`; `tests/test_tier5_refusal.py::test_missing_covariance_is_refused_with_no_fallback`; [screening ICD](icd/screening-api.md) |
| W2 | With the link cut, the edge console answered 40 requests at 18.9 ms (95th percentile), and all 11 DENIED checks passed on two real nodes. | [DDIL results: DENIED](ddil-results.md#denied) |
| W2 | After reconnecting, operator data converged in 2.65 s. Two conflicting triage edits were both kept as a CONFLICT, and a decision made offline against a superseded CDM was flagged REVIEW REQUIRED. | [DDIL results: DENIED](ddil-results.md#denied) |
| W2 | Over about 8 kbit/s with 600 ms latency, every event was visible as a summary in 6.2 s. The most urgent full CDM arrived in 9.3 s with earliest-deadline-first, against 137.4 s in arrival order: 14.8 times sooner over the same link with the same 51 records. Each figure is the median of 5 runs per mode, and the report lists every run. | [DDIL results: LIMITED](ddil-results.md#limited) |
| W2 | The order decides which record lands first, not how long the whole backlog takes: the same bytes over the same link take the same time in any order. Every record was delivered in 151.0 s in deadline order and 149.3 s in arrival order, and every event was verified in 48.0 s against 149.3 s. The backlog includes the 38 public element sets the hub offers by default. An earlier single run showed arrival order verifying every event sooner; its two modes had run on unequal links, which the scenario now checks for. | [DDIL results: LIMITED](ddil-results.md#limited) |
| W2 | Each event summary is at most 256 bytes, small enough to cross first. | [Requirements trace](traceability.md) (REQ-DDIL-003); `tests/sync/test_hub_edge.py::test_summaries_are_small_enough_to_send_first` |
| W2 | Over a link that dropped 8 times, 24 notes were written and 24 arrived on each node: none lost, none duplicated. | [DDIL results: INTERMITTENT](ddil-results.md#intermittent) |
| W2 | Over a degraded link (600 ± 200 ms latency, 32 kB/s) the nodes converged in 21.3 s. After a denial, the link re-established over the thin link in 5.5 s, and work done offline reached the hub in 7.4 s. | [DDIL results: DEGRADED](ddil-results.md#degraded), [RECOVERY](ddil-results.md#recovery) |
| W3 | With the real signing tool and no network, a tampered bundle, another key's signature, a missing signature and a wrong signer identity are all refused. | `deploy/bundle/selftest_signature.sh`; [Requirements trace](traceability.md) (REQ-SC-002) |
| W3 | A locally built bundle, signed with a throwaway key, installs in a network namespace with only loopback. The installed node reproduces the validation: 53 events and 0 missed refusals. The `airgap-install` CI job is configured to repeat this full install for each architecture. | `deploy/bundle/verify_offline.sh`; [Validation report](validation-report.md#6-the-applicability-gate-against-caras-own-verdicts); [Requirements trace](traceability.md) (VC-DEP-002) |
| W4 | On a real hub and edge, the edge received 38 public element sets through sync and computed 57 pass windows for a unit. Every message the hub's server carried was captured (147 messages, 44,828 bytes): none held the unit's id or coordinates, and a deliberate canary on the unit's subjects never arrived. All 10 checks passed, including controls that show the capture could see what the edge does export. | [DDIL results: OPSEC](ddil-results.md#opsec); `make opsec` |
| W4 | Afterwards the hub has no unit (its unit endpoint returns 404), and none of its 8 files holds the unit. On the edge, the unit rests in one file, readable only by the service. | [DDIL results: OPSEC](ddil-results.md#opsec); `tests/api/test_passes_api.py` |
| W5 | Every conjunction enters as a CCSDS CDM, and every NASA CDM parses and round-trips with its comments and units intact. | `tests/test_cdm_codec.py::test_every_nasa_cdm_parses_and_round_trips` |
| W5 | A second mission module replicates through the same, unmodified sync layer, and urgent conjunction data still crosses first. | `tests/sync/test_modules_share_sync.py::test_both_modules_arrive_intact_through_one_unmodified_agent` |
| W5 | Two independent pass providers pass one conformance suite; rise and set agree with a brute-force oracle to within 2 s. | [Requirements trace](traceability.md) (REQ-PASS-001); `tests/conformance/test_pass_providers.py::test_rise_and_set_agree_with_the_oracle_within_two_seconds` |
| W5 | The trace covers 54 requirements: 54 verified, 0 unverified, and 0 broken references. | [Requirements trace](traceability.md) |
| W6 | The AI package may not import the risk engine, the CDM codec, numpy or scipy. An import contract (`lint-imports`) fails the build if it does. | [Requirements trace](traceability.md) (REQ-AI-001); `.importlinter` |
| W6 | An AI-written answer that states a number the tool results do not contain is withheld. The template answer is shown instead, with the unsupported number named. | `tests/ai/test_grounding.py::test_an_invented_number_is_caught`; `tests/ai/test_assistant.py::test_an_ungrounded_ai_answer_is_withheld_and_the_facts_shown` |
| W6 | Hosted AI runs only with an allow-listed UNCLASSIFIED marking (no caveat), operator opt-in and a usable measured link, and never for a question that holds a position. A DENIED link or a caveated or classified marking never calls a hosted service. | `tests/ai/test_policy.py::test_tier_table`; `tests/ai/test_assistant.py::test_denied_or_classified_never_calls_a_hosted_service` |
| W6 | Routing is scored on 60 labelled requests. The always-available local rules pick the right tool for 0.460 of in-scope requests, which is the gap a model has to close. No hosted-model score is published, because none has been run. | [AI routing eval](ai-eval.md) |

## 5. Risks and mitigations

| Risk | Mitigation | Status |
|---|---|---|
| Real CDM access is not granted, or arrives late | CDMs are the single input contract, so a new source is one adapter. The engine is validated on NASA's published operational CDMs. Exercise data is labelled EXERCISE at the source. | Open. No live CDM feed is connected. |
| The refusal threshold was tuned on the same events it is scored on | The validation report states this next to the result. The next step is a held-out test set and a port of CARA's own usage-violation check. | Open, disclosed. |
| Events the 2D method cannot handle get no number at all | Refusing is the safe failure. The 3D method CARA publishes is the documented next step. | Detection built; 3D method not built. |
| Operators are not authenticated | Decisions are signed per node today. A site identity provider (CAC/PIV) at the front proxy would bind them to people. | Open; listed in the plan of action and milestones. |
| The link between nodes is not encrypted | The NATS templates leave a place for mutual TLS. Configure it before connecting any real link. | Open. |
| Annotations (triage status, assignee, note) are not signed, so a peer that can reach the hub can erase one | The decision log is signed and is the record of what was decided. Signing the annotations, or authenticating peers on the link, would close the gap. | Open; a test records it, and `SECURITY.md` lists it. |
| Removing the newest AI-audit lines while a node is stopped goes undetected | An edit, a deletion or a truncation made while the node runs is detected. Anchoring the chain's head outside the file would close the gap. | Open; `SECURITY.md` lists it. |
| The unit's position leaks through a path the test does not exercise | Four layers keep it on the edge (data model, application, storage, transport), and the OPSEC scenario checks the wire and the hub's files. The hub does not yet also refuse those subjects from its side. | Shown between one hub and one edge; more nodes and hub-side denial not yet. |
| A gap between passes is read as "safe" | Every gap is labelled "not observed by catalogued imagers", and the console says uncatalogued and non-public sensors are outside the model. | Built. |
| Hosted AI at a classified site | Policy blocks hosted AI unless the marking is exactly `UNCLASSIFIED` or `UNCLASSIFIED // EXERCISE`; a caveat such as CUI keeps it local. The air-gap bundle carries no hosted AI libraries. The assistant can be switched off. | Built and tested. |
| The release path has never run end to end | Each step has been run locally, and the release workflow is checked statically. The first tagged release is the test. | Open. |
| The pinned trust root goes stale when Sigstore rotates keys | Verification then fails loudly, never open. The refresh procedure is documented. | Built; the refresh is manual. |
| A hosted routing model may not beat the local rules | The routing eval scores any router on the same labelled set. A model is adopted only if a real run shows it earns its place. | The eval is built; no hosted run yet. |

## 6. What it would take to field

What is demonstrated here, and what fielding would still require.

| Area | Demonstrated | Still required |
|---|---|---|
| Data | NASA's published CDMs, a scripted exercise scenario, and a public element-set snapshot | Real CDM access under its terms, an ingest adapter for that source, and acceptance testing with operators |
| Identity | Node-level signatures on every decision | Operator authentication (CAC/PIV or the site's identity provider), so each decision is bound to a person |
| Transport | A real leaf link, shaped to DENIED, DEGRADED, LIMITED and INTERMITTENT conditions on one machine | TLS on the leaf link, site key management, and testing on real tactical and satellite links |
| Packaging | A signed bundle that installs a standalone node with no network; hub and edge messaging configuration as templates | A packaged messaging service and configuration for hub and edge roles, and a first signed release |
| Pass module | The pass engine, the edge-local service, the console tab, and the OPSEC scenario between one hub and one edge | Review of the imaging catalog and its assumptions by the unit, hub-side denial of the unit's subjects, and the OPSEC test on the fielded topology |
| AI | Local rules and templates, scored on the routing eval; the policy that allows hosted tiers only under an allow-listed UNCLASSIFIED marking with no caveat, tested with the hosted adapters on mock transports | A scored run of the hosted routing model; a local model for classified networks, if the eval shows it earns its place; an assessment with the CDAO toolkit |
| Accreditation | A draft security plan, assessment results and a plan of action and milestones generated from tests; a STIG role for the host | An authorizing official, a security categorization, a STIG scan of a real host, and an authorization to operate |
| Pipeline | CI configured for tests, import contracts, the trace, the security package and the supply-chain gates; each step run locally | CI running on a hosted service, and the release workflow run on a tag |

**A sensible first step** is a bounded pilot on an exercise network: one hub and one edge, a real CDM feed under its terms, operator authentication at the proxy, and TLS on the leaf link. The pilot would re-run the DDIL and OPSEC scenarios on the real link and publish the results the same way this repository does.

## 7. Policy alignment

Only authorities checked against a primary or official source are cited. Sentinel is not an acquisition program and has not been assessed against any of them. What follows maps its design to their language.

**Modular open systems (10 U.S.C. §4401).** The statute requires major defense acquisition programs to use a modular open system approach "to enable incremental development and enhance competition, innovation, and interoperability", and asks the same of other programs to the maximum extent practicable. It defines the approach as a modular design with modular system interfaces, verified to comply with widely supported, consensus-based standards where suitable, in an architecture where components can be added, removed or replaced. In Sentinel:

- the interfaces are CCSDS standards: CDMs for conjunctions, OMMs for element sets and OEMs for ephemerides;
- import contracts keep the modules apart, and the build fails if one is broken;
- two pass providers are held to one conformance suite;
- the sync layer carries a second mission module without a line changed.

**DoD AI Ethical Principles (adopted February 2020).** The five principles are Responsible, Equitable, Traceable, Reliable and Governable.

- *Responsible:* a person confirms every AI draft before it is recorded.
- *Traceable:* every ask and confirm is in a hash-chained audit log, and each decision carries its router, confidence and model.
- *Reliable:* the AI has one explicit use (routing to catalogued tools and phrasing their output), and that use is tested. The local router is scored; no hosted router has been scored yet.
- *Governable:* the assistant can be switched off. It drops to local rules by itself when the link or the marking requires, and it cannot reach the maths.
- *Equitable:* not assessed. The eval set's limits are written down in `evals/README.md`.

**CDAO Responsible AI Toolkit.** The Chief Digital and Artificial Intelligence Office released the Responsible AI (RAI) Toolkit in November 2023. It is a voluntary process that tracks how well an AI project aligns with responsible-AI best practices and the Department's AI Ethical Principles. Its current page calls it the AI Assurance (AIA) Toolkit. Sentinel has not been through it. A program would bring it the routing eval, the guard tests and the audit log.

**Continuous authorization (cATO).** The Department's February 2022 memorandum *Continuous Authorization to Operate (cATO)* names three competencies: an approved DevSecOps reference design, active cyber defense, and continuous monitoring of Risk Management Framework controls. Sentinel shows part of the third, in miniature: each test run turns its evidence into OSCAL assessment results and a plan of action and milestones. It has neither of the other two, and it is not authorized.

## References

1. 10 U.S.C. §4401, "Requirement for modular open system approach in major defense acquisition programs; definitions." <https://uscode.house.gov/view.xhtml?req=granuleid%3AUSC-prelim-title10-section4401&num=0&edition=prelim>
2. U.S. Department of Defense, "DOD Adopts Ethical Principles for Artificial Intelligence," press release, February 2020. <https://www.defense.gov/News/Releases/Release/Article/2091996/dod-adopts-ethical-principles-for-artificial-intelligence/>
3. DoD Chief Digital and Artificial Intelligence Office, "CDAO Releases Responsible AI (RAI) Toolkit for Ensuring Alignment With RAI Best Practices," November 2023. The toolkit: <https://www.tradewindai.com/rai-toolkit>
4. U.S. Department of Defense, memorandum, "Continuous Authorization to Operate (cATO)," February 2022. <https://media.defense.gov/2022/Feb/03/2002932852/-1/-1/0/CONTINUOUS-AUTHORIZATION-TO-OPERATE.PDF>
5. NASA CARA's published test cases are vendored unmodified under `fixtures/cara/`, with their licence and provenance. See the [validation report](validation-report.md).
