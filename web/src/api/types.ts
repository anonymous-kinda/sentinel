// Mirrors the node API (sentinel/conjunction/service.py). tests/api/test_api.py
// pins the server side of this contract.

export type Method = "FOSTER_ESTES_2D" | "REFUSED";
export type Band = "RED" | "AMBER" | "GREEN" | "UNASSESSED";
export type DataClass = "REAL" | "DERIVED" | "EXERCISE";
export type RefusalReason =
  | "NO_COVARIANCE"
  | "NO_HBR"
  | "INVALID_COVARIANCE"
  | "ILL_CONDITIONED_COVARIANCE"
  | "LOW_RELATIVE_VELOCITY"
  | "TCA_INCONSISTENT"
  | "CURVILINEAR_UNCERTAINTY";

export interface Assessment {
  method: Method;
  pc: number | null;
  pc_max: number | null;
  dilution_flag: boolean;
  dilution_margin: number | null;
  miss_distance_m: number;
  relative_speed_m_s: number;
  hbr_m: number | null;
  inputs_hash: string;
  refusal_reason: RefusalReason | null;
  diagnostics: Record<string, unknown>;
}

export interface ObjectRef {
  id: string;
  name: string | null;
}

export interface EventSummary {
  event_id: string;
  data_class: DataClass;
  primary: ObjectRef;
  secondary: ObjectRef;
  tca: string;
  mcp: string;
  time_to_tca_s: number;
  time_to_mcp_s: number;
  band: Band;
  worst_case_band: Band | null;
  consequence: "ROUTINE" | "WATCH" | "SERIOUS" | "CRITICAL";
  needs_attention: boolean;
  assessment: Assessment;
  originator: string | null;
  originator_pc: number | null;
  cdm_count: number;
  latest_cdm_sha256: string;
  latest_message_id: string | null;
  /** Edge nodes: how this node knows the event. */
  verification?: "LOCAL" | "VERIFIED" | "UPDATING" | "MISMATCH" | "HUB_ASSERTED";
  /** One line readable over a voice net (hub-asserted summaries). */
  voice?: string;
}

export interface HistoryEntry {
  sha256: string;
  message_id: string | null;
  creation_date: string | null;
  received_at: string;
  source: string;
  tca: string;
  originator_pc: number | null;
  hbr_source: string | null;
  warnings: { code: string; detail: string; key?: string | null }[];
  assessment: Assessment;
}

export interface EventDetail {
  summary: EventSummary;
  history: HistoryEntry[];
  asserted_by?: string;
  engine_version: string;
  policy: { red_pc: number; amber_pc: number; mcp_lead_time_s: number; urgent_window_s: number };
}

export interface Encounter {
  available: boolean;
  reason?: string;
  model_applies?: boolean;
  refusal_reason?: RefusalReason | null;
  hbr_m?: number;
  mu_m?: [number, number];
  cov_2d_m2?: [[number, number], [number, number]];
  sigma_major_m?: number;
  sigma_minor_m?: number;
  major_axis_angle_rad?: number;
  miss_distance_m?: number;
  relative_speed_m_s?: number;
  tca_adjustment_s?: number;
  curvilinear_ratio?: number;
  k_star?: number | null;
}

export interface DilutionCurve {
  available?: boolean;
  model_applies?: boolean;
  log10_k?: number[];
  pc?: number[];
  k_star?: number;
  pc_at_k1?: number;
  pc_max?: number;
  diluted?: boolean;
}

export interface Trajectory {
  tca: string;
  note: string;
  primary: [number, number, number, number][];
  secondary: [number, number, number, number][];
}

export interface NodeInfo {
  node_id: string;
  role: string;
  version: string;
  engine_version: string;
  marking: string;
  clock: string;
  now: string;
  read_only: boolean;
  demo_controls: boolean;
  modules: string[];
  policy: EventDetail["policy"];
}

export interface ValidationRow {
  case_id: string;
  primary: string;
  secondary: string;
  sentinel_pc: number;
  cara_pc2d: number;
  cara_nc3d: number;
  rel_error: number;
  cara_says_2d_valid: boolean;
  sentinel_default: Method;
  refusal_reason: RefusalReason | null;
  relative_speed_m_s: number;
}

export interface Validation {
  available: boolean;
  reason?: string;
  source?: string;
  operational_count?: number;
  worst_rel_error?: number;
  median_rel_error?: number;
  confusion?: { tp: number; fn: number; fp: number; tn: number };
  rows?: ValidationRow[];
  alfano?: { case_id: string; sentinel_pc: number; cara_pc2d: number; rel_error: number }[];
  alfano_worst_rel_error?: number;
  calibration_note?: string;
}

interface LogEntryBase {
  dot: [string, number];
  lamport: number;
  wall_time: string;
  event_ref: { event_id: string; cdm_sha256?: string; inputs_hash?: string; message_id?: string };
  author: string;
  node: string;
  signature_valid: boolean;
  digest: string;
  review_required: boolean;
}

export interface DecisionBody {
  decision: string;
  rationale?: string;
  /** An AI draft an operator confirmed: router, confidence, model, audit sequence. */
  drafted_by?: Record<string, unknown>;
}

/** A person settled a CONFLICT: the field, the value they wrote, and every
 *  concurrent value it superseded, each with who wrote it and where. */
export interface ResolutionBody {
  field: string;
  value: string;
  superseded: RegisterValue[];
}

/** A signed operator-log entry; its body depends on its kind. */
export type LogEntryView =
  | (LogEntryBase & { kind: "DECISION"; body: DecisionBody })
  | (LogEntryBase & { kind: "NOTE"; body: { text: string } })
  | (LogEntryBase & { kind: "RESOLUTION"; body: ResolutionBody });

export interface RegisterValue {
  dot: [string, number];
  v: string;
  by: string;
  node: string;
  at: string;
}

export interface OpsView {
  entries: LogEntryView[];
  annotations: Record<string, { values: RegisterValue[]; conflict: boolean }>;
  current_ref: { cdm_sha256: string; inputs_hash: string; message_id: string | null } | null;
  decisions: string[];
}

export interface LinkMonitorView {
  state: "CONNECTED" | "DEGRADED" | "LIMITED" | "DENIED" | "UNKNOWN";
  rtt_ms: number | null;
  rate_bytes_per_s: number | null;
  seconds_since_success: number | null;
  failures_in_row: number;
  bytes_total: number;
  exchanges: number;
}

export interface LinkInfo {
  role: string;
  hub_id: string | null;
  monitor: LinkMonitorView;
  emulation?: { preset: string; enabled: boolean; toxics: { name: string; type: string }[] } | null;
}

export interface QueueItem {
  event_id: string;
  sha: string;
  bytes: number;
  class: string;
  deadline: string | null;
  seconds_to_deadline: number | null;
  latest: boolean;
  status: string;
  eta_s: number | null;
}

export interface Arrival {
  event_id: string;
  sha: string;
  class: string;
  latest: boolean;
  bytes: number;
  wall_s: number;
  node_time: string;
  deadline: string | null;
  hash_ok: boolean;
  status: string;
  verification: string | null;
}

export interface SyncStatus {
  role: string;
  mode?: string;
  hub_id?: string;
  link?: LinkMonitorView;
  queue?: QueueItem[];
  arrivals?: Arrival[];
  arrivals_total?: number;
  summary_only?: string[];
  last_cycle?: Record<string, unknown>;
  requests?: Record<string, number>;
}

// ------------------------------------------------------------ assistant (M5)
export interface AiTier {
  router: "jev" | "deterministic";
  narrator: "claude" | "template";
  reason: string;
  link_state: string;
  marking: string;
}

export interface AiStatus {
  enabled: boolean;
  tier?: AiTier;
  link_source?: string;
  cloud_opt_in?: boolean;
  providers?: { jev: boolean; claude: boolean };
  models?: { jev: string | null; claude: string | null };
  min_confidence?: number;
}

export interface AiRoute {
  tool: string | null;
  args: Record<string, unknown>;
  confidence: number;
  provider: string;
  tool_probabilities: Record<string, number>;
  event_probabilities: Record<string, number>;
  detail: {
    model?: string;
    latency_ms?: number;
    request_bytes?: number;
    response_bytes?: number;
    consequential?: number;
  };
}

export interface AiAnswer {
  status: "answered" | "clarify" | "draft";
  text: string;
  tier: AiTier;
  route: AiRoute | null;
  facts: Record<string, unknown> | null;
  narrated_by: string | null;
  grounding: { ok: boolean; unsupported: string[] } | null;
  withheld: { narrator: string; unsupported: string[] } | null;
  alternatives: { tool?: string; event_id?: string; label?: string; p: number | null; description?: string }[];
  fallbacks: { from: string; to: string; reason: string }[];
  draft_id: string | null;
  audit_seq: number | null;
}

// ------------------------------------------------------------ passes (M3)
// Mirrors docs/icd/passes-api.md. Edge-local: the unit's position and its
// pass windows never leave the node (ADR-010). Times are ISO 8601 UTC.

export type PassSensor = "EO" | "SAR";

export interface PassUnit {
  unit_id: string;
  lat_deg: number;
  lon_deg: number;
  alt_m: number;
  reaction_time_min: number;
}

export interface PassWindow {
  norad_id: number;
  name: string;
  sensor: PassSensor;
  rise: string;
  culmination: string;
  set: string;
  /** rise and set widened by the element-set timing pad */
  padded_start: string;
  padded_end: string;
  pad_s: number;
  max_elevation_deg: number;
  /** the elevation the imager's field of regard implies */
  mask_elevation_deg: number;
  element_age_days: number;
  /** element set older than 3 days */
  stale: boolean;
  /** EO: unit lit at culmination. SAR: null (no daylight rule for radar). */
  sunlit: boolean | null;
  /** counts against the unit: SAR, or EO with the unit lit */
  usable: boolean;
}

/** Time not observed by catalogued imagers. Never an all-clear. */
export interface UnobservedGap {
  start: string;
  end: string;
  duration_s: number;
  /** a stale element set bounds or overlaps it */
  low_confidence: boolean;
}

export interface SkippedImager {
  norad_id: number;
  name: string;
  reason: string;
}

export interface PassesView {
  unit: PassUnit;
  start: string;
  end: string;
  provider: string;
  /** the gap label, shown verbatim */
  label: string;
  windows: PassWindow[];
  gaps: UnobservedGap[];
  next_unobserved: UnobservedGap | null;
  catalog: { imagers: number; skipped: SkippedImager[] };
  elements: { oldest_age_days: number | null; newest_age_days: number | null; stale: number };
}

export interface CatalogImager {
  norad_id: number;
  name: string;
  sensor: PassSensor;
  /** field of regard: a planning assumption, sourced in `basis` */
  max_off_nadir_deg: number;
  gsd_m: number | null;
  basis: string;
  element_epoch: string | null;
  element_age_days: number | null;
  stale: boolean;
}

export interface PassCatalog {
  imagers: CatalogImager[];
  skipped: SkippedImager[];
}

/** Visualization only: never an input to a window or a gap. */
export interface PassTrack {
  norad_id: number;
  positions_ecef_m: [number, number, number][];
  step_s: number;
  note: string;
}
