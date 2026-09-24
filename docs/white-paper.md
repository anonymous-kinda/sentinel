# Sentinel: collision-risk decisions that hold up when the link does not

*Capability white paper for program offices, S6/G6 staffs and space operations units.*

> **Read this first.** Sentinel is an open-source demonstration. It is not fielded, not accredited and not endorsed by any government organization, and no operator has used it on a real mission. Every number in the proof points below comes from a report the repository generates, and each one links to that report. Section 6 lists what fielding would still take.

## Summary

A satellite operator gets warnings that a tracked object may pass close to one of their spacecraft. They must decide, before the maneuver commit point, whether to spend propellant to avoid it. Two things go wrong in practice. The probability of collision can look reassuring for the wrong reason. And the tools that compute it assume a network that a deployed unit will not always have.

Sentinel is a decision aid built for that call. It computes collision risk with NASA's published method, checks itself against NASA's published results, and refuses to show a number the method cannot support. Each node keeps working when its link is cut. When the link is thin, the record due soonest crosses first. AI helps the operator ask questions and read answers, but it never computes a number. A disconnected site can prove the software is authentic before it installs anything.

## Win themes

- **W1. Numbers you can defend.** Sentinel matches NASA's published results and refuses, with a stated reason, any probability the method cannot support.
- **W2. Works when the link does not.** A cut-off node keeps working; on a thin link, the decision due soonest crosses first.
- **W3. AI that cannot invent a number.** The assistant routes and phrases, validated code computes, and a person decides.
- **W4. Trusted without a network.** A disconnected site verifies the signature offline, against a pinned trust root, before anything is unpacked.
- **W5. Open seams, traced evidence.** Standard formats at every seam, and a requirement trace that CI regenerates and fails on missing evidence.

## 1. The operational problem

**The decision.** Warnings arrive as Conjunction Data Messages (CDMs), in the international CCSDS format. Each event arrives as a series of messages, reissued as tracking improves. The operator has until the maneuver commit point to decide whether to maneuver. That deadline does not move because the network went down.

**The number can mislead.** Probability of collision (Pc) comes from how uncertain both objects' positions are. Past a certain point, *more* uncertainty gives a *lower* Pc: the probability is smeared so thin that little of it lands on the objects. This is called dilution. A low Pc can mean "we know these objects will miss" or "we barely know where they are". Those are opposite situations that print similar numbers. Public element sets (TLEs and their successors) carry no uncertainty at all, so they cannot support a Pc, and NASA says so.

**The network is not guaranteed.** Conjunction assessment tools are mostly hosted services. A ground station at a deployed site, a ship, or any denied or degraded link loses the tool exactly when the decision is due. When the link returns, the backlog usually crosses in arrival order, so the urgent record waits behind routine traffic. Two operators who changed the same event while apart often find that one change was silently overwritten.

**AI adds a new way to be wrong.** A language model is good at understanding a question and phrasing an answer. It is unreliable at arithmetic. An assistant that lets a model state a collision probability has put an unauditable number in front of the person who decides whether to burn propellant.

## 2. The approach

**One bundle, three roles.** The same signed bundle installs a cloud hub, a forward edge node or a standalone node. The role is configuration, not a separate build. Every node serves its own console from its own data. The console makes no request beyond its own node, so it works on a network with no route to the internet.

**Honest risk numbers.** Each node reads CDMs in the CCSDS standard format and computes Pc with the Foster-Estes method, ported from the software NASA's Conjunction Assessment Risk Analysis (CARA) team publishes. It also computes the worst-case Pc over all uncertainty scalings and flags dilution. Where the method does not apply, it refuses with a named reason and the value that tripped the check: missing or invalid uncertainty, low relative speed, or uncertainty that bends with the orbit. A refusal is shown as a refusal, never as zero.

**Disconnected, degraded, intermittent, limited.** Nodes connect over NATS leaf links. Reference data (CDMs) is pulled by the edge in mission priority: a small summary of every event first, then full records by earliest maneuver deadline. The edge re-assesses each record itself and compares its answer with the hub's. Operator data (triage, notes, decisions) uses state-based replicated data types: nothing is lost, and concurrent edits are shown as a CONFLICT instead of one silently winning. Decisions are signed per node and hash-chained. A decision made offline against data that has since changed is flagged REVIEW REQUIRED.

**AI that cannot compute.** The assistant turns an operator's words into one call to a catalogued tool. Sentinel's own validated code computes the facts, and the assistant phrases them. Local rules and templates always work with no network. Hosted models (a routing model and a language model) are optional. They are used only with an UNCLASSIFIED marking, operator opt-in and a usable measured link. Any number in an AI-written answer must match the tool output, or the answer is withheld. The assistant only drafts; a person confirms before anything is recorded.

**An overhead-pass module for ground units.** A second mission module shows when catalogued public imaging satellites can observe a ground unit, and the gaps between. The unit's position is meant never to leave the edge node. Today that is enforced by configuration; a test on the wire is planned. The engine and console tab are built; the edge-local service that connects them is being built now.

**A supply chain a disconnected site can check.** Releases are signed in CI without a long-lived key, with build provenance and software bills of materials attached. Every install path verifies the signature against a pinned trust root with no network, before unpacking. A vulnerability gate fails on any finding that has no reviewed exception.

**Evidence as code.** A SysML v2 model holds the requirements, and CI regenerates the requirement-to-evidence trace from it. A security package in OSCAL (a draft system security plan, assessment results and a plan of action and milestones) is generated from each test run.

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
| Let a model answer with numbers | Gives the AI no code path to the maths and withholds any answer with an unsupported number | The operator can trust every number on the screen came from validated code |
| Verify an install online, or not at all | Verifies offline against a pinned trust root, before unpacking | A disconnected site can check authenticity itself |
| Write compliance documents by hand | Generates the trace and the security package from test evidence; unbuilt work shows as planned | Reviewers see what is proven and what is not |

## 4. Proof points

Each proof point names its theme and links its evidence. Numbers come only from the generated reports: the [validation report](validation-report.md), the [DDIL results](ddil-results.md), the [AI routing eval](ai-eval.md) and the [requirements trace](traceability.md).

| Theme | Proof point | Evidence |
|---|---|---|
| W1 | On 53 real operational conjunctions that NASA CARA published, Sentinel's Pc matches CARA's value with a worst relative error of 1.5e-08. | [Validation report](validation-report.md#5-nasa-cara-53-real-operational-conjunctions); `tests/test_tier3_cara_validation.py::test_pc2d_matches_published_cara_value` |
| W1 | CARA flags 29 of those 53 events as outside the 2D method. Sentinel refuses all 29 and returns a Pc for none of them. It also refuses 5 events CARA would compute. The threshold was set on this same set of events, and the report says so. | [Validation report](validation-report.md#6-the-applicability-gate-against-caras-own-verdicts); `tests/test_tier3_cara_validation.py::test_gate_refuses_every_event_cara_says_2d_cannot_handle` |
| W1 | On the refused events above 100 m/s, CARA's own 3D result differs from the 2D value by factors of 0.016 to 60,722. Those are the numbers the refusals keep off the screen. | [Validation report](validation-report.md#6-the-applicability-gate-against-caras-own-verdicts) |
| W1 | The worst-case Pc matches its closed form to a relative error of 4.17e-14, and inflating the uncertainty by an order of magnitude lowers Pc and sets the dilution flag. | [Validation report](validation-report.md#3-maximum-probability-of-collision); `tests/test_tier4_dilution.py::test_inflating_covariance_by_one_order_of_magnitude_lowers_pc_and_sets_flag` |
| W1 | Element-set screening lists each close approach and states on every line that the Pc is refused. Fed back into the engine, each approach is refused for missing uncertainty data. | `tests/screening/test_cli_screen.py::test_each_approach_is_listed_with_its_pc_refused_and_written_as_a_derived_cdm`; `tests/test_tier5_refusal.py::test_missing_covariance_is_refused_with_no_fallback` |
| W2 | With the link cut, the edge console answered 40 requests at 2.7 ms (95th percentile), and all 11 DENIED checks passed on two real nodes. | [DDIL results: DENIED](ddil-results.md#denied) |
| W2 | After reconnecting, operator data converged in 2.36 s. Two conflicting triage edits were both kept as a CONFLICT, and a decision made offline against a superseded CDM was flagged REVIEW REQUIRED. | [DDIL results: DENIED](ddil-results.md#denied) |
| W2 | Over about 8 kbit/s with 600 ms latency, every event was visible as a summary in 2.5 s. The most urgent full CDM arrived in 5.5 s with earliest-deadline-first, against 38.2 s in arrival order: 6.9 times sooner over the same link with the same 13 records. | [DDIL results: LIMITED](ddil-results.md#limited) |
| W2 | Each event summary is at most 256 bytes, small enough to cross first. | [Requirements trace](traceability.md) (REQ-DDIL-003); `tests/sync/test_hub_edge.py::test_summaries_are_small_enough_to_send_first` |
| W2 | Over a link that dropped 8 times, 24 notes were written and 24 arrived on each node: none lost, none duplicated. | [DDIL results: INTERMITTENT](ddil-results.md#intermittent) |
| W2 | After a denial, the link re-established over the thin link in 5.5 s, and work done offline reached the hub in 7.3 s. | [DDIL results: RECOVERY](ddil-results.md#recovery) |
| W3 | The AI package may not import the risk engine, the CDM codec, numpy or scipy. This is an import contract that CI enforces. | [Requirements trace](traceability.md) (REQ-AI-001); `.importlinter` |
| W3 | An AI-written answer that states a number the tool results do not contain is withheld. The template answer is shown instead, with the unsupported number named. | `tests/ai/test_grounding.py::test_an_invented_number_is_caught`; `tests/ai/test_assistant.py::test_an_ungrounded_ai_answer_is_withheld_and_the_facts_shown` |
| W3 | Hosted AI runs only with an UNCLASSIFIED marking, operator opt-in and a usable measured link. A DENIED link or a classified marking never calls a hosted service. | `tests/ai/test_policy.py::test_tier_table`; `tests/ai/test_assistant.py::test_denied_or_classified_never_calls_a_hosted_service` |
| W3 | Routing is scored on 60 labelled requests. The always-available local rules pick the right tool for 0.460 of in-scope requests, which is the gap a model has to close. No hosted-model score is published, because none has been run. | [AI routing eval](ai-eval.md) |
| W4 | With the real signing tool and no network, a tampered bundle, another key's signature, a missing signature and a wrong signer identity are all refused. | `deploy/bundle/selftest_signature.sh`; [Requirements trace](traceability.md) (REQ-SC-002) |
| W4 | A locally built bundle, signed with a throwaway key, installs in a network namespace with only loopback. The installed node reproduces the validation: 53 events and 0 missed refusals. This runs on a developer machine; no CI job runs the full install yet. | `deploy/bundle/verify_offline.sh`; [Validation report](validation-report.md#6-the-applicability-gate-against-caras-own-verdicts); [Requirements trace](traceability.md) (VC-DEP-002, planned) |
| W4 | Build provenance is claimed at SLSA Build L2, not L3, and the supply-chain page says why. | [Supply chain](supply-chain.md) |
| W5 | Every conjunction enters as a CCSDS CDM, and every NASA CDM parses and round-trips with its comments and units intact. | `tests/test_cdm_codec.py::test_every_nasa_cdm_parses_and_round_trips` |
| W5 | A second mission module replicates through the same, unmodified sync layer, and urgent conjunction data still crosses first. | `tests/sync/test_modules_share_sync.py::test_both_modules_arrive_intact_through_one_unmodified_agent` |
| W5 | Two independent pass providers pass one conformance suite; rise and set agree with a brute-force oracle to within 2 s. | [Requirements trace](traceability.md) (REQ-PASS-001); `tests/conformance/test_pass_providers.py::test_rise_and_set_agree_with_the_oracle_within_two_seconds` |
| W5 | The trace covers 54 requirements: 49 verified, 5 unverified because their evidence is not built yet, and 0 broken references. | [Requirements trace](traceability.md) |

## 5. Risks and mitigations

| Risk | Mitigation | Status |
|---|---|---|
| Real CDM access is not granted, or arrives late | CDMs are the single input contract, so a new source is one adapter. The engine is validated on NASA's published operational CDMs. Exercise data is labelled EXERCISE at the source. | Open. No live CDM feed is connected. |
| The refusal threshold was tuned on the same events it is scored on | The validation report states this next to the result. The next step is a held-out test set and a port of CARA's own usage-violation check. | Open, disclosed. |
| Events the 2D method cannot handle get no number at all | Refusing is the safe failure. The 3D method CARA publishes is the documented next step. | Detection built; 3D method not built. |
| Operators are not authenticated | Decisions are signed per node today. A site identity provider (CAC/PIV) at the front proxy would bind them to people. | Open; listed in the plan of action and milestones. |
| The link between nodes is not encrypted | The NATS templates leave a place for mutual TLS. Configure it before connecting any real link. | Open. |
| The ground unit's position could leave the edge | Leaf permissions deny that traffic by configuration. A harness scenario that proves it on the wire is planned. | Configuration only. |
| Hosted AI at a classified site | Policy blocks hosted AI unless the marking is UNCLASSIFIED. The air-gap bundle carries no hosted AI libraries. The assistant can be switched off. | Built and tested. |
| The pinned trust root goes stale when Sigstore rotates keys | Verification then fails loudly, never open. The refresh procedure is documented. | Built; the refresh is manual. |
| The vulnerability database changes day to day | This is intended: a scan that passed yesterday may fail today, and the gate stops the release. | Built. |
| A hosted routing model may not beat the local rules | The routing eval scores any router on the same labelled set. A model is adopted only if a real run shows it earns its place. | The eval is built; no hosted run yet. |

## 6. What it would take to field

What is demonstrated here, and what fielding would still require.

| Area | Demonstrated | Still required |
|---|---|---|
| Data | NASA's published CDMs, a scripted exercise scenario, and a public element-set snapshot | Real CDM access under its terms, an ingest adapter for that source, and acceptance testing with operators |
| Identity | Node-level signatures on every decision | Operator authentication (CAC/PIV or the site's identity provider), so each decision is bound to a person |
| Transport | A real leaf link, shaped to DENIED, DEGRADED, LIMITED and INTERMITTENT conditions on one machine | TLS on the leaf link, site key management, and testing on real tactical and satellite links |
| Packaging | A signed bundle that installs a standalone node with no network; hub and edge messaging configuration as templates | A packaged messaging service and configuration for hub and edge roles |
| Pass module | The pass engine, two providers under one contract, and the console tab | The edge-local pass service, the on-the-wire OPSEC test, and review of the imaging catalog by the unit |
| AI | Local rules and templates; hosted tiers only on unclassified networks | A local model for classified networks, if the eval shows it earns its place; an assessment with the CDAO toolkit |
| Accreditation | A draft security plan, assessment results and a plan of action and milestones generated from tests; a STIG role for the host | An authorizing official, a security categorization, a STIG scan of a real host, and an authorization to operate |

**A sensible first step** is a bounded pilot on an exercise network: one hub and one edge, a real CDM feed under its terms, operator authentication at the proxy, and TLS on the leaf link. The pilot would re-run the DDIL scenarios on the real link and publish the results the same way this repository does.

## 7. Policy alignment

Only authorities we could check against a primary or official source are cited. Sentinel is not an acquisition program and has not been assessed against any of them. What follows maps its design to their language.

**Modular open systems (10 U.S.C. §4401).** The statute requires major defense acquisition programs to use a modular open system approach "to enable incremental development and enhance competition, innovation, and interoperability", and asks the same of other programs to the maximum extent practicable. It defines the approach as a modular design with modular system interfaces, verified to comply with widely supported, consensus-based standards where suitable, in an architecture where components can be added, removed or replaced. In Sentinel:

- the interfaces are CCSDS standards: CDMs for conjunctions, OMMs for element sets and OEMs for ephemerides;
- import contracts keep the modules apart, and CI enforces them;
- two pass providers are held to one conformance suite;
- the sync layer carries a second mission module without a line changed.

**DoD AI Ethical Principles (adopted February 2020).** The five principles are Responsible, Equitable, Traceable, Reliable and Governable.

- *Responsible:* a person confirms every AI draft before it is recorded.
- *Traceable:* every ask and confirm is in a hash-chained audit log, and each decision carries its router, confidence and model.
- *Reliable:* the AI has one explicit use (routing to catalogued tools and phrasing their output), and that use is tested and scored.
- *Governable:* the assistant can be switched off. It drops to local rules by itself when the link or the marking requires, and it cannot reach the maths.
- *Equitable:* not assessed. The eval set's limits are written down in `evals/README.md`.

**CDAO Responsible AI Toolkit.** The Chief Digital and Artificial Intelligence Office released the Responsible AI (RAI) Toolkit in November 2023. It is a voluntary process that tracks how well an AI project aligns with responsible-AI best practices and the Department's AI Ethical Principles. Its current page calls it the AI Assurance (AIA) Toolkit. Sentinel has not been through it. A program would bring it the routing eval, the guard tests and the audit log.

**Continuous authorization (cATO).** The Department's February 2022 memorandum *Continuous Authorization to Operate (cATO)* names three competencies: an approved DevSecOps reference design, active cyber defense, and continuous monitoring of Risk Management Framework controls. Sentinel shows part of the third, in miniature: every CI run turns test evidence into OSCAL assessment results and a plan of action and milestones. It has neither of the other two, and it is not authorized.

## References

1. 10 U.S.C. §4401, "Requirement for modular open system approach in major defense acquisition programs; definitions." <https://uscode.house.gov/view.xhtml?req=granuleid%3AUSC-prelim-title10-section4401&num=0&edition=prelim>
2. U.S. Department of Defense, "DOD Adopts Ethical Principles for Artificial Intelligence," press release, February 2020. <https://www.defense.gov/News/Releases/Release/Article/2091996/dod-adopts-ethical-principles-for-artificial-intelligence/>
3. DoD Chief Digital and Artificial Intelligence Office, "CDAO Releases Responsible AI (RAI) Toolkit for Ensuring Alignment With RAI Best Practices," November 2023. The toolkit: <https://www.tradewindai.com/rai-toolkit>
4. U.S. Department of Defense, memorandum, "Continuous Authorization to Operate (cATO)," February 2022. <https://media.defense.gov/2022/Feb/03/2002932852/-1/-1/0/CONTINUOUS-AUTHORIZATION-TO-OPERATE.PDF>
5. NASA CARA's published test cases and software are vendored unmodified under `fixtures/cara/`, with their licence and provenance. See the [validation report](validation-report.md).
