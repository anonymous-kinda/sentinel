import { useId, useState } from "react";
import type { LogEntryView, OpsView, ResolutionBody } from "../api/types";
import { postJSON, useResource } from "../api/client";
import { dtg } from "../lib/format";
import { useAction } from "../lib/useAction";

const STATUSES = ["NEW", "WATCH", "MANEUVER_PLANNING", "NO_ACTION", "CLOSED"];

/** MANEUVER_PLANNING reads as "MANEUVER PLANNING". Free text, which a peer
 *  node's operator wrote, is shown exactly as written. */
const words = (value: unknown): string => {
  const text = String(value);
  return /^[A-Za-z_]+$/.test(text) ? text.replaceAll("_", " ") : text;
};

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
  const { busy, error, run } = useAction();

  if (!data) return null;
  const status = data.annotations.triage_status;
  const refresh = () => setLocal((n) => n + 1);

  /** Resolves true when the node accepted the write. */
  const act = async (fn: () => Promise<unknown>) => {
    const done = await run(fn, "Operator data write failed", { event_id: eventId });
    if (done) refresh();
    return done;
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
            <b>{words(v.v)}</b>
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
                {words(s)}
              </button>
            ))}
          </div>
        )}
      </div>

      {!readOnly && (
        <form
          className="decision-form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await act(() => postJSON(`/api/events/${encodeURIComponent(eventId)}/decision`, { decision, rationale }))) setRationale("");
          }}
        >
          <select value={decision} onChange={(e) => setDecision(e.target.value)} aria-label="Decision">
            {data.decisions.map((d) => (
              <option key={d} value={d}>
                {words(d)}
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
            <LogEntry key={e.digest} entry={e} />
          ))}
      </ol>
    </section>
  );
}

function LogEntry({ entry: e }: { entry: LogEntryView }) {
  const labelId = useId();
  return (
    <li className={`log-entry kind-${e.kind.toLowerCase()}`} aria-labelledby={labelId}>
      <div className="log-head">
        <b id={labelId}>{e.kind === "DECISION" ? words(e.body.decision ?? "") : e.kind}</b>
        {e.review_required && (
          <span className="chip chip-review" title="Made against a CDM that has since been superseded. Re-examine before acting on it.">
            REVIEW REQUIRED
          </span>
        )}
        <span className={`sig ${e.signature_valid ? "sig-ok" : "sig-bad"}`} title={`Ed25519 signature by node ${e.node}; digest ${e.digest.slice(0, 16)}`}>
          {e.signature_valid ? "✓ signed" : "✗ signature"}
        </span>
      </div>
      <EntryBody entry={e} />
      <div className="muted log-meta">
        {e.author} on {e.node} · {dtg(e.wall_time)}
        {e.event_ref.message_id ? ` · against ${e.event_ref.message_id}` : ""}
      </div>
    </li>
  );
}

function EntryBody({ entry: e }: { entry: LogEntryView }) {
  if (e.kind === "RESOLUTION") return <Resolution body={e.body} />;
  const text = e.kind === "DECISION" ? e.body.rationale : e.body.text;
  return text ? <div className="log-body">{text}</div> : null;
}

/** Which field a person settled, to what, and every concurrent value it
 *  superseded, with who wrote each and on which node. */
function Resolution({ body }: { body: ResolutionBody }) {
  const superseded = Array.isArray(body.superseded) ? body.superseded : [];
  return (
    <div className="log-body">
      {words(body.field)} set to <b>{words(body.value)}</b>, superseding:
      <ul className="superseded" aria-label="Superseded values">
        {superseded.map((v, i) => (
          <li key={i}>
            <b>{words(v.v)}</b>{" "}
            <span className="muted">
              by {v.by} on {v.node} · {dtg(v.at)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
