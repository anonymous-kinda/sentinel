package SentinelArchitecture {
    doc /*
     * Sentinel's structure: what the parts are, what crosses between them, and
     * which part satisfies which requirement. Each part definition names the
     * code that implements it. Interfaces between modules carry published
     * CCSDS messages where a standard exists (ADR-001); the sync envelope is
     * the one interface without one, and says so (system-design.md s5).
     */
    private import ScalarValues::*;
    private import SentinelRequirements::*;

    // ================================================================ items
    enum def DataClass {
        doc /* Stamped on every record (repo rule). */
        enum REAL;
        enum DERIVED;
        enum EXERCISE;
    }

    enum def AssessmentMethod {
        enum FOSTER_ESTES_2D;
        enum REFUSED;
    }

    enum def RefusalReason {
        enum LOW_RELATIVE_VELOCITY;
        enum INVALID_COVARIANCE;
        enum ILL_CONDITIONED_COVARIANCE;
        enum NO_COVARIANCE;
        enum TCA_INCONSISTENT;
        enum CURVILINEAR_UNCERTAINTY;
        enum NO_HBR;
    }

    enum def VerificationStanding {
        doc /* Where an edge stands on a hub-supplied event (ADR-008). */
        enum HUB_ASSERTED;
        enum VERIFIED;
        enum MISMATCH;
    }

    item def Cdm {
        doc /* CCSDS 508.0-B-1 Conjunction Data Message, KVN, original bytes kept.
             * The canonical internal contract (ADR-001). State in km, covariance
             * in m^2. */
        attribute dataClass : DataClass;
    }

    item def Omm {
        doc /* CCSDS Orbit Mean-Elements Message (CCSDS 502.0-B ODM family), as
             * CelesTrak publishes it. For pass timing and screening geometry,
             * never for a probability of collision (ADR-002). */
        attribute dataClass : DataClass;
    }

    item def Oem {
        doc /* CCSDS Orbit Ephemeris Message (CCSDS 502.0-B ODM family): a
             * tabulated ephemeris for a pass provider. */
        attribute dataClass : DataClass;
    }

    item def AssessedConjunction {
        doc /* The engine's output (risk-engine-design.md s2): a Pc never travels
             * without its method. */
        attribute pc : Real[0..1];
        attribute pcMax : Real[0..1];
        attribute dilutionFlag : Boolean;
        attribute method : AssessmentMethod;
        attribute refusalReason : RefusalReason[0..1];
        attribute inputsHash : String;
    }

    item def EventSummary {
        doc /* One event in at most 256 bytes: identity, deadline (maneuver
             * commit point), consequence, and one voice-readable line. Sent
             * before any full record (ADR-006). */
        attribute eventId : String;
        attribute verification : VerificationStanding;
    }

    item def Decision {
        doc /* An operator decision: an immutable, Ed25519-signed, per-node
             * hash-chained entry in a grow-only CRDT log (ADR-005). */
        attribute author : String;
        attribute supersededCdm : Boolean;
    }

    item def TriageStatus {
        doc /* A multi-value register: concurrent writes are all kept and shown
             * as a CONFLICT (ADR-005). */
    }

    item def UnitPosition {
        doc /* A ground unit's location and reaction time. Edge-local only. */
    }

    item def PassWindow {
        doc /* Rise, culmination and set of one imager over one unit, padded for
             * element-set age and labelled stale when it is old. Edge-local. */
        attribute pad_s : Real;
        attribute stale : Boolean;
    }

    // ================================================================ ports
    port def CdmIngestPort {
        doc /* Source adapters in: Space-Track, CelesTrak, an operator upload. */
        in item cdm : Cdm;
    }

    port def ElementSetPort {
        in item omm : Omm;
        in item oem : Oem;
    }

    port def SyncPort {
        doc /* What a hub offers an edge over the leaf link: summaries first,
             * then full CDMs in triage order, and operator data both ways by
             * CRDT anti-entropy. Request/reply over NATS; no standard exists
             * for this envelope, and none is claimed. */
        out item summary : EventSummary;
        out item cdm : Cdm;
        inout item decision : Decision;
        inout item triage : TriageStatus;
    }

    port def OperatorPort {
        doc /* The console: assessments out, decisions and triage in. */
        out item assessment : AssessedConjunction;
        out item window : PassWindow;
        in item decision : Decision;
        in item unit : UnitPosition;
    }

    port def HostedAiPort {
        doc /* Jev (routing) and Claude (phrasing), used only when the AI tier
             * allows it. No risk number crosses this port. */
    }

    interface def LeafLink {
        doc /* One NATS leafnode connection, hub to edge. Leaf permissions deny
             * node.>, unit.> and passes.> across it (ADR-004, ADR-009). */
        end hubSide : SyncPort;
        end edgeSide : ~SyncPort;
    }

    // =============================================================== states
    enum def LinkStateKind {
        enum CONNECTED;
        enum DEGRADED;
        enum LIMITED;
        enum DENIED;
        enum UNKNOWN;
    }

    state def LinkState {
        doc /* Measured, never configured (sentinel/linkstate/monitor.py), from
             * what the sync agent observes. DENIED takes precedence, then
             * LIMITED, then DEGRADED. A link that returns after a denial is a
             * new link: the old averages are forgotten and it is measured
             * afresh. Guards name their conditions; the thresholds are the
             * bindings below. */
        attribute roundTrip_s : Real;
        attribute rate_bytes_per_s : Real;
        attribute silence_s : Real;
        attribute deniedAfter_s : Real;
        attribute failuresInRow : Integer;
        attribute succeeded : Boolean;

        attribute failing : Boolean = failuresInRow > 0;
        attribute slow : Boolean = roundTrip_s >= 1.0;
        attribute thin : Boolean = rate_bytes_per_s < 4000.0;
        attribute silent : Boolean = silence_s > deniedAfter_s and failing;

        entry; then UNKNOWN;

        state UNKNOWN { doc /* Nothing measured yet, or a link just back from a denial. */ }
        state CONNECTED { doc /* Exchanges succeed; round trip under 1 s. */ }
        state DEGRADED { doc /* Exchanges succeed, but slowly (1 s or more) or flakily. */ }
        state LIMITED { doc /* Exchanges succeed, but below 4 kB/s. */ }
        state DENIED { doc /* No successful exchange within the grace period. */ }

        transition unknownToDenied first UNKNOWN if failing and not succeeded then DENIED;
        transition unknownToConnected first UNKNOWN if succeeded and not slow and not thin then CONNECTED;
        transition unknownToDegraded first UNKNOWN if succeeded and slow and not thin then DEGRADED;
        transition unknownToLimited first UNKNOWN if succeeded and thin then LIMITED;
        transition becomesDegraded first CONNECTED if slow or failing then DEGRADED;
        transition becomesLimited first CONNECTED if thin then LIMITED;
        transition degradedToLimited first DEGRADED if thin then LIMITED;
        transition degradedRecovers first DEGRADED if not slow and not failing then CONNECTED;
        transition limitedToDegraded first LIMITED if not thin and slow or not thin and failing then DEGRADED;
        transition limitedRecovers first LIMITED if not thin and not slow and not failing then CONNECTED;
        transition lostWhileConnected first CONNECTED if silent then DENIED;
        transition lostWhileDegraded first DEGRADED if silent then DENIED;
        transition lostWhileLimited first LIMITED if silent then DENIED;
        transition deniedReturns first DENIED if succeeded and not failing then UNKNOWN;
    }

    state def AiTier {
        doc /* What the AI tier policy permits (sentinel/ai/policy.py): a pure
             * function of the measured link, the marking and operator opt-in.
             * Within a permitted tier, a provider that is not configured, or a
             * hosted call that fails, falls back to the local tier within the
             * same answer. A hub or standalone node has no upstream link to
             * measure and is treated as CONNECTED, labelled as assumed. */
        attribute link : LinkStateKind;
        attribute unclassified : Boolean;
        attribute hostedOptIn : Boolean;

        attribute hostedAllowed : Boolean = unclassified and hostedOptIn;
        attribute linkRoutable : Boolean =
            link == LinkStateKind::CONNECTED or link == LinkStateKind::DEGRADED or link == LinkStateKind::LIMITED;
        attribute linkCarriesProse : Boolean = link == LinkStateKind::CONNECTED or link == LinkStateKind::DEGRADED;

        entry; then LOCAL_ONLY;

        state LOCAL_ONLY {
            doc /* Deterministic router (slash commands and keywords) and
                 * templates. Always available. */
        }
        state HOSTED_ROUTING {
            doc /* Jev may route: its answer is a few probabilities, small enough
                 * for a LIMITED link. Templates phrase. */
        }
        state HOSTED_ROUTING_AND_PROSE {
            doc /* Jev may route and Claude may phrase. */
        }

        transition localToProse first LOCAL_ONLY if hostedAllowed and linkCarriesProse then HOSTED_ROUTING_AND_PROSE;
        transition localToRouting first LOCAL_ONLY if hostedAllowed and linkRoutable and not linkCarriesProse then HOSTED_ROUTING;
        transition proseToRouting first HOSTED_ROUTING_AND_PROSE if hostedAllowed and linkRoutable and not linkCarriesProse then HOSTED_ROUTING;
        transition routingToProse first HOSTED_ROUTING if hostedAllowed and linkCarriesProse then HOSTED_ROUTING_AND_PROSE;
        transition proseToLocal first HOSTED_ROUTING_AND_PROSE if not hostedAllowed or not linkRoutable then LOCAL_ONLY;
        transition routingToLocal first HOSTED_ROUTING if not hostedAllowed or not linkRoutable then LOCAL_ONLY;
    }

    // ================================================================ parts
    part def Bus { doc /* sentinel/bus: the Bus protocol; NATS on a node, in-process in tests (ADR-004). */ }
    part def NatsServer { doc /* The node's own nats-server; it, not the application, holds the leaf link. */ }
    part def CdmCodec { doc /* sentinel/cdm: CCSDS 508.0-B-1 KVN codec and admission policy. */ }
    part def RiskEngine { doc /* sentinel/risk: Foster-Estes 2D Pc, TCA refinement, dilution, applicability gate. Pure maths. */ }
    part def ConjunctionService { doc /* sentinel/conjunction: ingest, events, triage policy, summaries. */ }
    part def ValidationService { doc /* sentinel/validation: re-runs the NASA CARA comparison with the engine the node is running. */ }
    part def TriagePolicy { doc /* sentinel/triage: class, deadline, consequence - all sync knows of a mission. */ }
    part def SyncAgent { doc /* sentinel/sync/agent.py: the edge's priority pull (ADR-008). */ }
    part def SyncServer { doc /* sentinel/sync/server.py: the hub's manifest, fetch and ops exchange. */ }
    part def DecisionLog { doc /* sentinel/crdt: signed, hash-chained, grow-only decision log. */ }
    part def TriageRegisters { doc /* sentinel/crdt: multi-value registers for triage status and annotations. */ }
    part def OperatorData {
        doc /* sentinel/ops: operator data service, persistence and anti-entropy. */
        part decisionLog : DecisionLog;
        part registers : TriageRegisters;
    }
    part def LinkMonitor { doc /* sentinel/linkstate: measures the link to the hub. */ }
    part def TierPolicy { doc /* sentinel/ai/policy.py */ }
    part def Router { doc /* sentinel/ai/router.py, router_jev.py: one catalogued tool call per request. */ }
    part def Narrator { doc /* sentinel/ai/narrate.py, narrate_claude.py: phrases tool facts. */ }
    part def GroundingGuard { doc /* sentinel/ai/grounding.py: every number must come from the tools. */ }
    part def AiAssistant {
        doc /* sentinel/ai: routes to tools and phrases their facts; never computes. */
        part tierPolicy : TierPolicy;
        part router : Router;
        part narrator : Narrator;
        part groundingGuard : GroundingGuard;
        port hostedAi : HostedAiPort;
        exhibit state tier : AiTier;
    }
    part def AuditLog { doc /* sentinel/audit: hash-chained JSON Lines. */ }
    part def PassModule {
        doc /* sentinel/passes: pass windows for a unit from element sets, behind
             * the PassProvider contract. Runs at the edge. */
        port elements : ElementSetPort;
    }
    part def OperatorConsole {
        doc /* sentinel/api and web/: the node's own API and console, strict CSP,
             * offline globe imagery. */
        port operator : OperatorPort;
    }

    part def SentinelNode {
        doc /* One node: hub or edge is configuration, not a different build. */
        port cdmIn : CdmIngestPort;
        port downstream : SyncPort;       // served to edges (hub role)
        port upstream : ~SyncPort;        // pulled from a hub (edge role)

        part natsServer : NatsServer;
        part bus : Bus;
        part cdmCodec : CdmCodec;
        part riskEngine : RiskEngine;
        part conjunctions : ConjunctionService;
        part validation : ValidationService;
        part triage : TriagePolicy;
        part syncAgent : SyncAgent;
        part syncServer : SyncServer;
        part operatorData : OperatorData;
        part linkMonitor : LinkMonitor;
        part assistant : AiAssistant;
        part auditLog : AuditLog;
        part passModule : PassModule;
        part console : OperatorConsole;

        exhibit state link : LinkState;
    }

    part def SentinelSystem {
        doc /* A hub (cloud or on-prem) and a deployed edge, joined by one leaf link. */
        part hub : SentinelNode;
        part edge : SentinelNode;
        interface leafLink : LeafLink connect hubSide ::> hub.downstream to edgeSide ::> edge.upstream;
    }

    part def Bundle {
        doc /* scripts/build_bundle.py, deploy/bundle: one tarball per CPU
             * architecture - hash-pinned wheels, console, NASA reference data,
             * pinned uv and nats-server, systemd units, offline installer. */
    }

    part def HubInfrastructure {
        doc /* deploy/aws/terraform and deploy/ansible: the cloud hub as code. */
    }

    part def ContinuousIntegration {
        doc /* .github/workflows/ci.yml: lint, module boundaries, the test
             * ladder, reproducible reports, the trace, secrets scanning. */
    }

    part def ReleasePipeline {
        doc /* Planned (M4): SBOMs, signed bundles and OSCAL evidence per release. */
    }

    part def DeliveryPipeline {
        part ci : ContinuousIntegration;
        part release : ReleasePipeline;
    }

    // ========================================================= the system
    part sentinel : SentinelSystem;
    part bundle : Bundle;
    part hubInfrastructure : HubInfrastructure;
    part delivery : DeliveryPipeline;

    // ========================================================= satisfaction
    // DEP
    satisfy oneCodebaseEveryRole by sentinel.hub;
    satisfy oneCodebaseEveryRole by sentinel.edge;
    satisfy offlineInstall by bundle;
    satisfy hubInfrastructureAsCode by hubInfrastructure;
    satisfy consoleNeverCallsOut by sentinel.edge.console;

    // MOSA
    satisfy cdmIsTheContract by sentinel.hub.cdmCodec;
    satisfy ingestPolicy by sentinel.hub.cdmCodec;
    satisfy ingestPolicy by sentinel.hub.conjunctions;
    satisfy boundariesEnforced by delivery.ci;
    satisfy passModuleIndependent by sentinel.edge.passModule;
    satisfy elementSetsAsOmm by sentinel.edge.passModule;
    satisfy ephemerisAsOem by sentinel.edge.passModule;
    satisfy secondModuleSharesSync by sentinel.edge.syncAgent;
    satisfy secondModuleSharesSync by sentinel.hub.syncServer;

    // DDIL
    satisfy consoleAvailableWhileDenied by sentinel.edge.console;
    satisfy consoleAvailableWhileDenied by sentinel.edge.natsServer;
    satisfy linkStateMeasured by sentinel.edge.linkMonitor;
    satisfy summariesFirst by sentinel.hub.syncServer;
    satisfy summariesFirst by sentinel.edge.syncAgent;
    satisfy urgentRecordFirst by sentinel.edge.syncAgent;
    satisfy urgentRecordFirst by sentinel.hub.triage;
    satisfy catchUpOrder by sentinel.edge.syncAgent;
    satisfy noDataLoss by sentinel.edge.syncAgent;
    satisfy noDataLoss by sentinel.edge.riskEngine;
    satisfy conflictsSurfaced by sentinel.edge.operatorData.registers;
    satisfy staleDecisionFlagged by sentinel.edge.operatorData;
    satisfy noDuplicateEntries by sentinel.edge.operatorData.decisionLog;
    satisfy degradedKeepsWorking by sentinel.edge;
    satisfy recoversOverThinLink by sentinel.edge.natsServer;
    satisfy signedDecisionLog by sentinel.edge.operatorData.decisionLog;
    satisfy nodeLocalEventsStayLocal by sentinel.edge.natsServer;
    satisfy nodeLocalEventsStayLocal by sentinel.edge.bus;

    // RISK
    satisfy caraAgreement by sentinel.hub.riskEngine;
    satisfy caraAgreement by sentinel.hub.validation;
    satisfy benchmarkAgreement by sentinel.hub.riskEngine;
    satisfy gateMatchesCara by sentinel.hub.riskEngine;
    satisfy refusalGates by sentinel.hub.riskEngine;
    satisfy noPcFromElementSets by sentinel.hub.riskEngine;
    satisfy noPcFromElementSets by sentinel.hub.cdmCodec;
    satisfy dilutionFlagged by sentinel.hub.riskEngine;
    satisfy numbersTraceToInputs by sentinel.hub.riskEngine;
    satisfy numbersTraceToInputs by sentinel.hub.console;
    satisfy integralAgainstOracles by sentinel.hub.riskEngine;
    satisfy encounterGeometry by sentinel.hub.riskEngine;

    // AI
    satisfy noPathToTheMaths by sentinel.edge.assistant;
    satisfy numbersGrounded by sentinel.edge.assistant.groundingGuard;
    satisfy draftsNeedConfirmation by sentinel.edge.assistant;
    satisfy draftsNeedConfirmation by sentinel.edge.operatorData.decisionLog;
    satisfy auditChain by sentinel.edge.auditLog;
    satisfy tierFollowsLinkAndMarking by sentinel.edge.assistant.tierPolicy;
    satisfy hostedFailureFallsBack by sentinel.edge.assistant.router;
    satisfy hostedFailureFallsBack by sentinel.edge.assistant.narrator;
    satisfy unsureMeansAsk by sentinel.edge.assistant;
    satisfy routingMeasured by sentinel.edge.assistant.router;

    // OPSEC
    satisfy unitPositionStaysAtEdge by sentinel.edge.natsServer;
    satisfy unitPositionStaysAtEdge by sentinel.edge.passModule;

    // PASS
    satisfy passTimingAccuracy by sentinel.edge.passModule;
    satisfy stalenessLabelled by sentinel.edge.passModule;
    satisfy sensorGeometry by sentinel.edge.passModule;
    satisfy passServiceAtEdge by sentinel.edge.console;
    satisfy passServiceAtEdge by sentinel.edge.passModule;
    satisfy providersInterchangeable by sentinel.edge.passModule;

    // SC
    satisfy sbom by delivery.release;
    satisfy signedBundles by delivery.release;
    satisfy signedBundles by bundle;
    satisfy oscalPackage by delivery.release;
    satisfy referenceDataUnmodified by delivery.ci;
    satisfy noSecretsCommitted by delivery.ci;
    satisfy auditableLogs by delivery.ci;
    satisfy generatedTrace by delivery.ci;
}
