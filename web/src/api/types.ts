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
