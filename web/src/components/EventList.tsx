import type { EventSummary } from "../api/types";
import { countdown, dtg, metres } from "../lib/format";
import { PcValue } from "./PcValue";
import { VerificationChip } from "./Verification";

export function BandChip({ band, worst }: { band: string; worst?: string | null }) {
  return (
    <span className="chips">
      <span className={`chip band-${band.toLowerCase()}`}>{band === "UNASSESSED" ? "NO PC" : band}</span>
      {worst && worst !== band && (
        <span className={`chip chip-outline band-${worst.toLowerCase()}`} title="Worst case over covariance scaling (diluted)">
          worst {worst}
        </span>
      )}
    </span>
  );
}

export function EventList({
  events,
  selected,
  onSelect,
  mode,
}: {
  events: EventSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
  mode: "active" | "past";
}) {
  if (events.length === 0) {
    return <div className="empty">No events.</div>;
  }
  return (
    <ul className="event-list" role="listbox" aria-label="Conjunction events">
      {events.map((e) => {
        const a = e.assessment;
        const pastMcp = e.time_to_mcp_s < 0 && mode === "active";
        return (
          <li
            key={e.event_id}
            role="option"
            aria-selected={selected === e.event_id}
            className={`event-row ${selected === e.event_id ? "selected" : ""} ${e.needs_attention ? "attention" : ""}`}
            onClick={() => onSelect(e.event_id)}
            onKeyDown={(k) => k.key === "Enter" && onSelect(e.event_id)}
            tabIndex={0}
          >
            <div className="row-top">
              {mode === "active" ? (
                <span className={`countdown ${pastMcp ? "past" : ""}`} title="Time to maneuver commit point">
                  MCP {countdown(e.time_to_mcp_s)}
                </span>
              ) : (
                <span className="countdown past">{dtg(e.tca)}</span>
              )}
              <span className="chips">
                <VerificationChip v={e.verification} />
                <BandChip band={e.band} worst={e.worst_case_band} />
              </span>
            </div>
            <div className="row-names">
              <span className="obj-primary">{e.primary.name ?? e.primary.id}</span>
              <span className="vs">×</span>
              <span className="obj-secondary">{e.secondary.name ?? e.secondary.id}</span>
            </div>
            <div className="row-bottom">
              <PcValue assessment={a} size="sm" />
              <span className="muted">{metres(a.miss_distance_m)}</span>
              {a.dilution_flag && <span className="chip chip-dil">DILUTED</span>}
              {a.method === "REFUSED" && <span className="chip chip-refused">{a.refusal_reason}</span>}
              <span className="muted right">{e.cdm_count} CDM</span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
