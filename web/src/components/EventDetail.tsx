import { useEffect, useState } from "react";
import type { DilutionCurve as Curve, Encounter, EventDetail as Detail } from "../api/types";
import { useResource } from "../api/client";
import { countdown, dtg, metres, REFUSAL_TEXT, sci, shortHash, speed } from "../lib/format";
import { BPlane } from "./BPlane";
import { DilutionCurve } from "./DilutionCurve";
import { HistorySpark } from "./HistorySpark";
import { BandChip } from "./EventList";
import { PcValue } from "./PcValue";
import { OpsPanel } from "./OpsPanel";
import { VerificationChip } from "./Verification";

export function EventDetail({
  eventId,
  version,
  slot,
  readOnly = true,
  hasOps = false,
}: {
  eventId: string;
  version: number;
  slot?: React.ReactNode;
  readOnly?: boolean;
  hasOps?: boolean;
}) {
  const { data: detail } = useResource<Detail>(`/api/events/${encodeURIComponent(eventId)}`, version);
  const { data: encounter } = useResource<Encounter>(`/api/events/${encodeURIComponent(eventId)}/encounter`, version);
  const { data: curve } = useResource<Curve>(`/api/events/${encodeURIComponent(eventId)}/dilution-curve`, version);
  const [log10k, setLog10k] = useState(0);

  useEffect(() => setLog10k(0), [eventId]);

  if (!detail) return <div className="empty">Loading…</div>;
  const s = detail.summary;
  const a = s.assessment;
  const latest = detail.history[detail.history.length - 1];
  const diag = a.diagnostics as Record<string, number | string | boolean | string[] | null>;

  if (!latest) {
    // Known on this node only from the hub's summary.
    return (
      <div className="detail">
        <header className="detail-head">
          <div className="detail-title">
            <span className="obj-primary">{s.primary.name ?? s.primary.id}</span>
            <span className="vs">×</span>
            <span className="obj-secondary">{s.secondary.name ?? s.secondary.id}</span>
          </div>
          <div className="detail-meta">
            <VerificationChip v="HUB_ASSERTED" />
            <span>TCA {dtg(s.tca)}</span>
            <span>
              MCP {dtg(s.mcp)} <b>{countdown(s.time_to_mcp_s)}</b>
            </span>
          </div>
        </header>
        <section className="headline">
          <PcValue assessment={a} size="lg" />
          <BandChip band={s.band} worst={s.worst_case_band} />
          <div className="kv-grid">
            <span>miss</span>
            <b>{metres(a.miss_distance_m)}</b>
            <span>rel. speed</span>
            <b>{speed(a.relative_speed_m_s)}</b>
          </div>
        </section>
        <section className="callout callout-asserted">
          <b>Asserted by {detail.asserted_by ?? "the hub"}, not computed here.</b> Only the summary has reached this node; no
          covariance travelled with it, so this node cannot have recomputed the Pc. The full CDM is in the sync queue and
          will be re-assessed on arrival.
          {s.voice && (
            <div className="voice" title="The summary as one line, readable over a voice net">
              {s.voice}
            </div>
          )}
        </section>
        {hasOps && <OpsPanel eventId={eventId} version={version} readOnly={readOnly} />}
      </div>
    );
  }

  return (
    <div className="detail">
      <header className="detail-head">
        <div className="detail-title">
          <span className="obj-primary">{s.primary.name ?? s.primary.id}</span>
          <span className="vs">×</span>
          <span className="obj-secondary">{s.secondary.name ?? s.secondary.id}</span>
        </div>
        <div className="detail-meta">
          <span className={`chip dc-${s.data_class.toLowerCase()}`}>{s.data_class}</span>
          <VerificationChip v={s.verification} />
          <span>TCA {dtg(s.tca)}</span>
          {s.time_to_tca_s < 0 ? (
            <span className="muted">historical event</span>
          ) : (
            <span>
              MCP {dtg(s.mcp)} <b className={s.time_to_mcp_s < 0 ? "past" : ""}>{countdown(s.time_to_mcp_s)}</b>
            </span>
          )}
        </div>
      </header>

      <section className="headline">
        <PcValue assessment={a} size="lg" />
        <BandChip band={s.band} worst={s.worst_case_band} />
        <div className="kv-grid">
          <span>miss</span>
          <b>{metres(a.miss_distance_m)}</b>
          <span>rel. speed</span>
          <b>{speed(a.relative_speed_m_s)}</b>
          <span>HBR</span>
          <b>{a.hbr_m !== null ? metres(a.hbr_m) : "-"}</b>
          <span>updates</span>
          <b>{s.cdm_count}</b>
        </div>
      </section>

      {a.method === "REFUSED" && (
        <section className="refusal">
          <h4>Refused: {a.refusal_reason}</h4>
          <p>{REFUSAL_TEXT[a.refusal_reason ?? ""] ?? ""}</p>
          <dl>
            {Object.entries(diag)
              .filter(([k]) => !["independence_assumed", "hbr_defaulted"].includes(k))
              .map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{typeof v === "number" ? (Math.abs(v) < 1e-3 || Math.abs(v) > 1e5 ? v.toExponential(3) : v.toPrecision(4)) : String(v)}</dd>
                </div>
              ))}
          </dl>
        </section>
      )}

      {a.dilution_flag && (
        <section className="callout callout-dil">
          <b>Diluted.</b> The operating point sits past the Pc peak (k* = {Number(diag.k_star).toPrecision(3)}): more
          uncertainty would <i>lower</i> this Pc. Treat it as a floor on ignorance, not evidence of safety, and weigh the
          worst case over covariance scaling shown beside it.
        </section>
      )}

      {slot}

      {hasOps && <OpsPanel eventId={eventId} version={version} readOnly={readOnly} />}

      <section className="plots">
        {encounter && <BPlane encounter={encounter} log10k={log10k} />}
        {curve && curve.log10_k ? (
          <DilutionCurve curve={curve} log10k={log10k} onChange={setLog10k} />
        ) : (
          <div className="plot-empty">No Pc(k) curve for this event.</div>
        )}
        <HistorySpark history={detail.history} />
      </section>

      <section className="provenance">
        <h4>Provenance</h4>
        <dl>
          <div>
            <dt>inputs hash</dt>
            <dd className="mono">{shortHash(a.inputs_hash, 16)}</dd>
          </div>
          <div>
            <dt>engine</dt>
            <dd className="mono">{detail.engine_version}</dd>
          </div>
          <div>
            <dt>latest CDM</dt>
            <dd className="mono">
              {latest.message_id} · sha256 {shortHash(latest.sha256)}
            </dd>
          </div>
          <div>
            <dt>originator</dt>
            <dd>
              {s.originator}
              {s.originator_pc !== null && (
                <>
                  {" "}
                  · asserted Pc {sci(s.originator_pc)} <span className="muted">(theirs, not Sentinel's)</span>
                </>
              )}
            </dd>
          </div>
          <div>
            <dt>HBR source</dt>
            <dd>{latest.hbr_source ?? "none"}</dd>
          </div>
          {typeof diag.tca_adjustment_s === "number" && (
            <div>
              <dt>TCA refinement</dt>
              <dd>
                {Math.abs(Number(diag.tca_adjustment_s) * 1000) < 0.0005 ? "0.000" : (Number(diag.tca_adjustment_s) * 1000).toFixed(3)} ms · miss at supplied TCA{" "}
                {metres(Number(diag.miss_distance_at_supplied_tca_m))}
              </dd>
            </div>
          )}
          {latest.warnings.length > 0 && (
            <div>
              <dt>admission warnings</dt>
              <dd>
                {latest.warnings.map((w, i) => (
                  <div key={i}>
                    {w.code}: {w.detail}
                  </div>
                ))}
              </dd>
            </div>
          )}
        </dl>
      </section>
    </div>
  );
}
