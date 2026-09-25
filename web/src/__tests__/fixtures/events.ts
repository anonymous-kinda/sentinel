import type { Assessment, EventDetail, EventSummary, NodeInfo } from "../../api/types";

// Hand-written conjunction payloads shaped like the node API's replies
// (sentinel/conjunction/service.py). The numbers are test data, not engine
// output.

export const assessment: Assessment = {
  method: "FOSTER_ESTES_2D",
  pc: 3.6e-5,
  pc_max: 2.0e-4,
  dilution_flag: false,
  dilution_margin: 0.3,
  miss_distance_m: 800,
  relative_speed_m_s: 14000,
  hbr_m: 20,
  inputs_hash: "abcdef0123456789abcdef",
  refusal_reason: null,
  diagnostics: { k_star: 1.4 },
};

export const diluted: Assessment = { ...assessment, dilution_flag: true, diagnostics: { k_star: 0.2 } };

export const refused: Assessment = {
  ...assessment,
  method: "REFUSED",
  pc: null,
  pc_max: null,
  refusal_reason: "NO_COVARIANCE",
  diagnostics: { missing_covariance_for: ["99118"] },
};

export function summary(overrides: Partial<EventSummary> = {}): EventSummary {
  return {
    event_id: "99001-99118-20260924T070000",
    data_class: "EXERCISE",
    primary: { id: "99001", name: "EX-SAT 1" },
    secondary: { id: "99118", name: "EX-DEB 118" },
    tca: "2026-09-24T19:00:00Z",
    mcp: "2026-09-24T17:00:00Z",
    time_to_tca_s: 28_000,
    time_to_mcp_s: 21_000,
    band: "AMBER",
    worst_case_band: null,
    consequence: "WATCH",
    needs_attention: true,
    assessment,
    originator: "SENTINEL-EXERCISE",
    originator_pc: null,
    cdm_count: 3,
    latest_cdm_sha256: "f".repeat(64),
    latest_message_id: "EX-118-3",
    verification: "LOCAL",
    ...overrides,
  };
}

export function detail(s: EventSummary = summary()): EventDetail {
  return {
    summary: s,
    history: [
      {
        sha256: s.latest_cdm_sha256,
        message_id: s.latest_message_id,
        creation_date: "2026-09-24T06:00:00Z",
        received_at: "2026-09-24T06:00:01Z",
        source: "upload",
        tca: s.tca,
        originator_pc: s.originator_pc,
        hbr_source: "CDM",
        warnings: [],
        assessment: s.assessment,
      },
    ],
    engine_version: "test",
    policy: { red_pc: 1e-4, amber_pc: 1e-5, mcp_lead_time_s: 7200, urgent_window_s: 43_200 },
  };
}

/** A hub that runs every console module. */
export const hubNode: NodeInfo = {
  node_id: "hub-1",
  role: "hub",
  version: "0.2.0",
  engine_version: "test",
  marking: "UNCLASSIFIED // EXERCISE",
  clock: "real",
  now: "2026-09-24T11:10:00Z",
  read_only: false,
  demo_controls: false,
  modules: ["conjunction", "ops", "sync"],
  policy: { red_pc: 1e-4, amber_pc: 1e-5, mcp_lead_time_s: 7200, urgent_window_s: 43_200 },
};
