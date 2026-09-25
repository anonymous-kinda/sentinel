package SentinelRequirements {
    doc /*
     * What Sentinel must do. Each requirement has a stable id, REQ-<AREA>-NNN,
     * that docs/traceability.md keys on. Areas:
     *
     *   DEP    one piece of software for cloud, edge and on-prem
     *   MOSA   modular interfaces on open standards (CCSDS CDM, OMM, OEM)
     *   DDIL   denied, degraded, intermittent and limited links
     *   RISK   the collision-risk engine against NASA CARA's published cases
     *   AI     AI decision support that cannot corrupt the decision
     *   OPSEC  what never leaves an edge node
     *   PASS   the Army overhead-pass module
     *   SC     supply chain and ATO evidence
     *
     * Every number in a criterion comes from the repository's own documents:
     * docs/ddil-results.md, docs/validation-report.md, docs/ai-eval.md,
     * docs/system-design.md and docs/risk-engine-design.md. Pass-module and
     * supply-chain targets are the M3 and M4 plan; their verification is
     * marked planned in verification.sysml until the evidence exists.
     */
    private import ScalarValues::*;

    // ------------------------------------------------------------------ DEP
    requirement <'REQ-DEP-001'> oneCodebaseEveryRole {
        doc /* The same software runs as a cloud hub, a deployed edge node or a
             * standalone on-prem node. The role is configuration, not a
             * separate build. */
    }

    requirement <'REQ-DEP-002'> offlineInstall {
        doc /* One bundle per CPU architecture (x86_64, aarch64) installs a node
             * with no network: dependencies come from hash-pinned wheels, and
             * the install is verified inside a network namespace that has only
             * loopback, where the node reproduces the NASA validation (53
             * events, zero false negatives) and serves the console. */
    }

    requirement <'REQ-DEP-003'> hubInfrastructureAsCode {
        doc /* The cloud hub's infrastructure is code, checked in CI: Terraform
             * formatted and validated, and the Ansible playbook syntax-checked. */
    }

    requirement <'REQ-DEP-004'> consoleNeverCallsOut {
        doc /* The console makes no request beyond its own node: it is served
             * under a same-origin Content-Security-Policy (default-src 'self'),
             * so the browser itself blocks any other origin. */
    }

    // ----------------------------------------------------------------- MOSA
    requirement <'REQ-MOSA-001'> cdmIsTheContract {
        doc /* Every conjunction enters as a CCSDS 508.0-B-1 Conjunction Data
             * Message (KVN), and nothing downstream of ingest depends on its
             * source. Every NASA CDM parses and round-trips with its comments
             * and units intact. */
    }

    requirement <'REQ-MOSA-002'> ingestPolicy {
        doc /* Input that would make an answer wrong is rejected or quarantined
             * with a named reason. Input that only makes it incomplete is
             * admitted with a warning. Both are recorded. */
    }

    requirement <'REQ-MOSA-003'> boundariesEnforced {
        doc /* Module boundaries are enforced in CI, not by convention: the bus
             * and triage know no mission module; sync, CRDTs, operator data and
             * link state know no mission module; the CDM codec depends on no
             * service above it; the risk engine does no I/O. */
    }

    requirement <'REQ-MOSA-004'> passModuleIndependent {
        doc /* The pass module depends on no conjunction, risk, CDM, sync, API or
             * AI code, so it can be replaced or competed on its own. */
    }

    requirement <'REQ-MOSA-005'> elementSetsAsOmm {
        doc /* Element sets enter as CCSDS Orbit Mean-Elements Messages (OMM);
             * a wrong element set is rejected with a named reason. */
    }

    requirement <'REQ-MOSA-006'> ephemerisAsOem {
        doc /* Tabulated ephemerides enter as CCSDS Orbit Ephemeris Messages
             * (OEM), read to the standard's grammar, with keywords outside the
             * supported subset refused rather than ignored. */
    }

    requirement <'REQ-MOSA-007'> secondModuleSharesSync {
        doc /* A second mission module replicates through the same, unmodified
             * sync layer, and urgent conjunction data still crosses first. */
    }

    // ----------------------------------------------------------------- DDIL
    requirement <'REQ-DDIL-001'> consoleAvailableWhileDenied {
        doc /* While the link to the hub is DENIED, the edge console stays
             * available with p95 latency below 200 ms, and operators keep
             * triaging and recording decisions locally. */
        attribute consoleP95_ms : Real;
        require constraint { consoleP95_ms < 200.0 }
    }

    requirement <'REQ-DDIL-002'> linkStateMeasured {
        doc /* The link state (CONNECTED, DEGRADED, LIMITED, DENIED, UNKNOWN) is
             * measured from real exchanges, never configured: a round trip of
             * 1 s or more is DEGRADED, throughput below 4 kB/s is LIMITED, and
             * no successful exchange within the grace period is DENIED. */
    }

    requirement <'REQ-DDIL-003'> summariesFirst {
        doc /* Over a LIMITED link (about 8 kbit/s plus 600 ms latency) every
             * event is visible as a summary of at most 256 bytes, marked
             * HUB-ASSERTED, before its full record arrives. */
        attribute summary_bytes : Integer;
        require constraint { summary_bytes <= 256 }
    }

    requirement <'REQ-DDIL-004'> urgentRecordFirst {
        doc /* Over a LIMITED link, full records cross earliest maneuver commit
             * point first: the most urgent event's full CDM arrives sooner than
             * in FIFO order over the same link with the same bytes. */
        attribute mostUrgentEdf_s : Real;
        attribute mostUrgentFifo_s : Real;
        require constraint { mostUrgentEdf_s < mostUrgentFifo_s }
    }

    requirement <'REQ-DDIL-005'> catchUpOrder {
        doc /* After a denial, catch-up is urgent before routine before history,
             * and earliest deadline first within urgent (Kendall tau of at
             * least 0.95 against deadline order). */
        attribute urgentKendallTau : Real;
        require constraint { urgentKendallTau >= 0.95 }
    }

    requirement <'REQ-DDIL-006'> noDataLoss {
        doc /* Nothing is lost across a denial or an intermittent link: every hub
             * CDM reaches the edge (the set difference is empty) and every event
             * is re-assessed at the edge and VERIFIED against what the hub
             * asserted. */
        attribute cdmsMissingAtEdge : Integer;
        require constraint { cdmsMissingAtEdge == 0 }
    }

    requirement <'REQ-DDIL-007'> conflictsSurfaced {
        doc /* Operator data converges after reconnect, and two people who changed
             * the same event's triage status while partitioned see a CONFLICT
             * naming both values, never last-writer-wins. */
    }

    requirement <'REQ-DDIL-008'> staleDecisionFlagged {
        doc /* A decision made offline against a CDM that has since been
             * superseded is flagged REVIEW REQUIRED. */
    }

    requirement <'REQ-DDIL-009'> noDuplicateEntries {
        doc /* Repeated link drops neither duplicate nor lose decision-log entries:
             * the count on both nodes equals the count written. */
    }

    requirement <'REQ-DDIL-010'> degradedKeepsWorking {
        doc /* Over a DEGRADED link (600 +/- 200 ms latency, 32 kB/s) both nodes
             * keep operating and converge, with no process restart. */
    }

    requirement <'REQ-DDIL-011'> recoversOverThinLink {
        doc /* After a denial the leaf link re-establishes over about 8 kbit/s,
             * and operator data written while denied reaches the hub. */
    }

    requirement <'REQ-DDIL-012'> signedDecisionLog {
        doc /* Decision-log entries are Ed25519-signed and hash-chained per node:
             * a tampered entry, an untrusted node or a reused dot with different
             * content is rejected, and an offline decision verifies at the hub. */
    }

    requirement <'REQ-DDIL-013'> nodeLocalEventsStayLocal {
        doc /* Each node serves its own console from its own data, and node-local
             * events (node.<id>.>) never cross a leaf link, so an edge never
             * shows the hub's events before it has fetched and verified them. */
    }

    // ----------------------------------------------------------------- RISK
    requirement <'REQ-RISK-001'> caraAgreement {
        doc /* The 2D probability of collision agrees with NASA CARA's published
             * Pc2D on all 53 operational events within a relative tolerance of
             * 1e-6, each CDM read through Sentinel's own parser from the
             * unmodified NASA files. */
        attribute worstRelativeError : Real;
        require constraint { worstRelativeError <= 1e-6 }
    }

    requirement <'REQ-RISK-002'> benchmarkAgreement {
        doc /* The engine reproduces CARA's Alfano (2009) benchmark cases within
             * CARA's own tolerance of 1e-3 relative and Omitron Case 1 within
             * 1e-6, and the Omitron Case 2 difference is explained by the
             * miss-distance convention. */
    }

    requirement <'REQ-RISK-003'> gateMatchesCara {
        doc /* No 2D Pc is returned for any event CARA flags as outside the 2D
             * method's validity (29 of 29 refused, none missed), and the
             * conservative refusals stay bounded. */
        attribute cara2dInvalidReturned : Integer;
        require constraint { cara2dInvalidReturned == 0 }
    }

    requirement <'REQ-RISK-004'> refusalGates {
        doc /* The engine never raises on bad data. It refuses with a named
             * reason (low relative velocity, invalid, ill-conditioned or missing
             * covariance, inconsistent TCA, curvilinear uncertainty, no hard-body
             * radius) and records the value that tripped the gate. */
    }

    requirement <'REQ-RISK-005'> noPcFromElementSets {
        doc /* No probability of collision without covariance: a CDM without it
             * degrades to geometry only, and the engine never falls back to an
             * element-set guess. */
    }

    requirement <'REQ-RISK-006'> dilutionFlagged {
        doc /* The engine computes the maximum Pc over covariance scaling and
             * flags the dilution region (k* below 1): inflating the covariance
             * by an order of magnitude lowers Pc and sets the flag, and a
             * dilution flag always comes with the maximum Pc. */
    }

    requirement <'REQ-RISK-007'> numbersTraceToInputs {
        doc /* A Pc never travels without its method, and every result carries a
             * stable inputs hash that changes when any input changes, through
             * the API and the assistant as well as the engine. */
    }

    requirement <'REQ-RISK-008'> integralAgainstOracles {
        doc /* The collision integral matches closed forms (the Rayleigh disk
             * mass, the optimal scale k* and the maximum Pc) and an independent
             * numerical oracle, scipy's dblquad in Cartesian coordinates, at a
             * relative tolerance of 1e-8. */
    }

    requirement <'REQ-RISK-009'> encounterGeometry {
        doc /* Frame rotation and encounter-plane geometry are right before any
             * probability is computed: orthonormal RTN bases, covariance round
             * trips, and a projected miss vector with no second component. */
    }

    // ------------------------------------------------------------------- AI
    requirement <'REQ-AI-001'> noPathToTheMaths {
        doc /* The AI layer cannot compute a risk number: it may not import the
             * risk engine, the CDM codec, numpy or scipy, and hosted AI SDKs are
             * confined to their adapters. */
    }

    requirement <'REQ-AI-002'> numbersGrounded {
        doc /* Every number in an AI-written answer matches, at the precision
             * stated, a number in the tool results or the operator's question.
             * Otherwise the answer is withheld and the template answer shown. */
    }

    requirement <'REQ-AI-003'> draftsNeedConfirmation {
        doc /* The assistant only drafts. A person confirms a draft, once, before
             * it becomes a signed decision carrying its provenance, and a draft
             * made against a superseded CDM cannot be confirmed. */
    }

    requirement <'REQ-AI-004'> auditChain {
        doc /* Every ask and every confirm is a line of a hash-chained audit log;
             * an edited or deleted line is detected. */
    }

    requirement <'REQ-AI-005'> tierFollowsLinkAndMarking {
        doc /* The AI tier is a pure function of the measured link, the
             * classification marking and operator opt-in: hosted AI needs an
             * allow-listed UNCLASSIFIED marking with no caveat, opt-in, and a
             * question that holds no position; Jev may route on CONNECTED,
             * DEGRADED or LIMITED; Claude may phrase on CONNECTED or DEGRADED;
             * DENIED is local only. */
    }

    requirement <'REQ-AI-006'> hostedFailureFallsBack {
        doc /* A hosted call gets one attempt. Any failure falls back to the
             * local tier within the same answer, and the answer says so. */
    }

    requirement <'REQ-AI-007'> unsureMeansAsk {
        doc /* Below 0.5 confidence in the tool or the event, or when an event tool has no event, the
             * assistant asks back with the top alternatives instead of acting. */
    }

    requirement <'REQ-AI-008'> routingMeasured {
        doc /* Routing is scored on 60 labelled requests through the assistant's
             * own confidence gate (accuracy, coverage, abstention, Brier score,
             * calibration error), the report is reproducible in CI, and no Jev
             * number is published without a real run. */
    }

    // ---------------------------------------------------------------- OPSEC
    requirement <'REQ-OPSEC-001'> unitPositionStaysAtEdge {
        doc /* An Army unit's position, and the pass windows computed from it,
             * never leave the edge node: the hub never receives unit.> or
             * passes.> traffic, whatever the link state. */
    }

    // ----------------------------------------------------------------- PASS
    requirement <'REQ-PASS-001'> passTimingAccuracy {
        doc /* Pass windows (rise, culmination, set) from element sets agree with
             * a brute-force oracle stepping at 1 s to within 2 s. */
        attribute timingError_s : Real;
        require constraint { timingError_s <= 2.0 }
    }

    requirement <'REQ-PASS-002'> stalenessLabelled {
        doc /* Every window is padded for element-set age (60 s plus 30 s per
             * day) and labelled stale once its element set is more than 3 days
             * old. */
    }

    requirement <'REQ-PASS-003'> sensorGeometry {
        doc /* The field of regard sets the elevation mask, the sun's elevation
             * matches the JPL ephemeris, and optical imagers need daylight while
             * radar imagers do not. */
    }

    requirement <'REQ-PASS-004'> passServiceAtEdge {
        doc /* The pass module is served by the edge node's own API: windows for
             * a unit are computed and answered on the edge, with no call to the
             * hub. */
    }

    requirement <'REQ-PASS-005'> providersInterchangeable {
        doc /* Pass providers are interchangeable behind one PassProvider
             * contract: each returns every window overlapping the interval with
             * its true rise and set, sorted by rise, and names itself. */
    }

    // ------------------------------------------------------------------- SC
    requirement <'REQ-SC-001'> sbom {
        doc /* Every release bundle ships a software bill of materials (SPDX and
             * CycloneDX). */
    }

    requirement <'REQ-SC-002'> signedBundles {
        doc /* Release bundles are signed, the signature verifies offline, and an
             * unsigned or altered bundle is never installed. */
    }

    requirement <'REQ-SC-003'> oscalPackage {
        doc /* An OSCAL system security plan and assessment results are generated
             * from CI evidence and validate. */
    }

    requirement <'REQ-SC-004'> referenceDataUnmodified {
        doc /* Vendored NASA reference data is used unmodified: its SHA-256
             * checksums are verified by the test suite, and expected values are
             * transcribed from it, never produced by running this code. */
    }

    requirement <'REQ-SC-005'> noSecretsCommitted {
        doc /* Every push is scanned for committed secrets across the whole
             * history. */
    }

    requirement <'REQ-SC-006'> auditableLogs {
        doc /* Every log call uses a constant message with values as structured
             * fields, so logs can be searched and alerted on by message. */
    }

    requirement <'REQ-SC-007'> generatedTrace {
        doc /* Requirement traceability is generated from this model in CI: a
             * reference to evidence that does not exist fails the build, and the
             * committed trace must match the regenerated one. */
    }
}
