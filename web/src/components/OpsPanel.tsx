import { useState } from "react";
import type { OpsView } from "../api/types";
import { postJSON, useResource } from "../api/client";
import { dtg } from "../lib/format";

const STATUSES = ["NEW", "WATCH", "MANEUVER_PLANNING", "NO_ACTION", "CLOSED"];

/**
 * Triage status and the decision log for one event.
 *
 * Both replicate between nodes as CRDTs. Two operators changing the status
 * while partitioned produces a CONFLICT that shows every value, who set it
 * and where - resolved by a person, never by a timestamp. Decisions are
 * signed entries; one made against a CDM that has since been superseded is
 * flagged REVIEW REQUIRED.
 */
export function OpsPanel({ eventId, version, readOnly }: { eventId: string; version: number; readOnly: boolean }) {
  const [local, setLocal] = useState(0);
  const { data } = useResource<OpsView>(`/api/events/${encodeURIComponent(eventId)}/ops`, version + local);
  const [decision, setDecision] = useState("MONITOR");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!data) return null;
  const status = data.annotations.triage_status;
  const refresh = () => setLocal((n) => n + 1);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setError(String((e as { payload?: { detail?: string } }).payload?.detail ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ops-panel">
      <h4>Triage and decisions</h4>
      <div className={`triage ${status.conflict ? "triage-conflict" : ""}`}>
        <div className="triage-head">
          <span>Status</span>
          {status.conflict && (
            <span className="chip chip-conflict" title="Concurrent edits on different nodes. Every value is kept until a person resolves it.">
              CONFLICT
            </span>
          )}
        </div>
        {status.values.length === 0 && <div className="muted">not triaged</div>}
        {status.values.map((v) => (
          <div key={v.dot.join(":")} className="triage-value">
            <b>{v.v.replaceAll("_", " ")}</b>
            <span className="muted">
              {v.by} on {v.node} · {dtg(v.at)}
            </span>
          </div>
        ))}
        {!readOnly && (
          <div className="triage-buttons">
            {STATUSES.map((s) => (
              <button
                key={s}
                disabled={busy}
                className="btn-small"
                onClick={() => act(() => postJSON(`/api/events/${encodeURIComponent(eventId)}/annotation`, { field: "triage_status", value: s }))}
                title={status.conflict ? "Setting a status after seeing both values resolves the conflict" : undefined}
              >
                {s.replaceAll("_", " ")}
              </button>
            ))}
          </div>
        )}
      </div>

      {!readOnly && (
        <form
          className="decision-form"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => postJSON(`/api/events/${encodeURIComponent(eventId)}/decision`, { decision, rationale }));
            setRationale("");
          }}
        >
          <select value={decision} onChange={(e) => setDecision(e.target.value)} aria-label="Decision">
            {data.decisions.map((d) => (
              <option key={d} value={d}>
                {d.replaceAll("_", " ")}
              </option>
            ))}
          </select>
          <input
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="Rationale (recorded, signed)"
            aria-label="Rationale"
          />
          <button type="submit" disabled={busy} className="btn-primary">
            Record decision
          </button>
        </form>
      )}
      {error && <div className="form-error">{error}</div>}

      <ol className="log">
        {data.entries.length === 0 && <li className="muted">No decisions recorded.</li>}
        {data.entries
          .slice()
          .reverse()
          .map((e) => (
            <li key={e.digest} className={`log-entry kind-${e.kind.toLowerCase()}`}>
              <div className="log-head">
                <b>{e.kind === "DECISION" ? (e.body.decision ?? "").replaceAll("_", " ") : e.kind}</b>
                {e.review_required && (
                  <span className="chip chip-review" title="Made against a CDM that has since been superseded. Re-examine before acting on it.">
                    REVIEW REQUIRED
                  </span>
                )}
                <span className={`sig ${e.signature_valid ? "sig-ok" : "sig-bad"}`} title={`Ed25519 signature by node ${e.node}; digest ${e.digest.slice(0, 16)}`}>
                  {e.signature_valid ? "✓ signed" : "✗ signature"}
                </span>
              </div>
              {(e.body.rationale || e.body.text) && <div className="log-body">{e.body.rationale || e.body.text}</div>}
              <div className="muted log-meta">
                {e.author} on {e.node} · {dtg(e.wall_time)}
                {e.event_ref.message_id ? ` · against ${e.event_ref.message_id}` : ""}
              </div>
            </li>
          ))}
      </ol>
    </section>
  );
}
