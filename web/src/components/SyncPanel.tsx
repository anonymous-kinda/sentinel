import type { SyncStatus } from "../api/types";
import { useResource } from "../api/client";
import { countdown } from "../lib/format";

/**
 * What the sync agent is doing, live: the priority queue in the order it
 * will be fetched (class, then earliest deadline), each item's ETA at the
 * measured rate, and the arrival log. On a thin link this is the view that
 * shows why the most urgent event arrives first.
 */
export function SyncPanel({ version }: { version: number }) {
  const { data } = useResource<SyncStatus>("/api/sync", version);
  if (!data) return <div className="empty">Loading…</div>;
  if (data.role !== "edge") {
    return (
      <div className="sync">
        <p className="lede">
          This node is the <b>hub</b>. Edges pull from it: summaries first, then full CDMs earliest-deadline-first, and
          operator data by CRDT anti-entropy in both directions.
        </p>
        <div className="cards">
          {Object.entries(data.requests ?? {}).map(([k, v]) => (
            <div className="card" key={k}>
              <span className="card-k">{k} requests served</span>
              <span className="card-v">{v}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }
  const link = data.link!;
  const queue = data.queue ?? [];
  const arrivals = (data.arrivals ?? []).slice().reverse();
  return (
    <div className="sync">
      <p className="lede">
        Edge sync from <b>{data.hub_id}</b> in <b>{data.mode?.toUpperCase()}</b> mode. Summaries of every event arrive
        first; full CDMs follow in priority order - urgent before routine before history, earliest maneuver commit point
        first. If the measured link cannot deliver a record before its deadline, the event is held as SUMMARY-ONLY rather
        than spending the link on it.
      </p>
      <div className="cards">
        <div className="card">
          <span className="card-k">link (measured)</span>
          <span className={`card-v link-text-${link.state.toLowerCase()}`}>{link.state}</span>
        </div>
        <div className="card">
          <span className="card-k">round trip</span>
          <span className="card-v">{link.rtt_ms !== null ? `${Math.round(link.rtt_ms)} ms` : "-"}</span>
        </div>
        <div className="card">
          <span className="card-k">payload rate</span>
          <span className="card-v">{link.rate_bytes_per_s ? `${Math.round(link.rate_bytes_per_s).toLocaleString()} B/s` : "-"}</span>
        </div>
        <div className="card">
          <span className="card-k">records received</span>
          <span className="card-v">{data.arrivals_total}</span>
        </div>
      </div>
      <div className="sync-grid">
        <div>
          <h3>Queue - fetch order</h3>
          {queue.length === 0 && <div className="muted">Up to date with the hub.</div>}
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>class</th>
                <th>event</th>
                <th>record</th>
                <th>bytes</th>
                <th>to deadline</th>
                <th>ETA</th>
                <th>status</th>
              </tr>
            </thead>
            <tbody>
              {queue.map((q, i) => (
                <tr key={q.sha} className={q.status === "SUMMARY_ONLY" ? "warn" : ""}>
                  <td className="num">{i + 1}</td>
                  <td>{q.class.replace("_", " ")}</td>
                  <td className="mono">{q.event_id.slice(0, 22)}</td>
                  <td>{q.latest ? "latest" : "history"}</td>
                  <td className="num">{q.bytes.toLocaleString()}</td>
                  <td className="num">{q.seconds_to_deadline !== null ? countdown(q.seconds_to_deadline) : "-"}</td>
                  <td className="num">{q.eta_s !== null ? `${q.eta_s} s` : "-"}</td>
                  <td>{q.status.replace("_", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h3>Arrivals</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>t (s)</th>
                <th>class</th>
                <th>event</th>
                <th>bytes</th>
                <th>check</th>
              </tr>
            </thead>
            <tbody>
              {arrivals.map((a) => (
                <tr key={a.sha + a.wall_s}>
                  <td className="num">{a.wall_s}</td>
                  <td>{a.class.replace("_", " ")}</td>
                  <td className="mono">{a.event_id.slice(0, 22)}</td>
                  <td className="num">{a.bytes.toLocaleString()}</td>
                  <td className={a.hash_ok ? "good" : "bad"}>
                    {a.hash_ok ? "sha256 ✓" : "sha256 ✗"} {a.verification === "VERIFIED" ? "· verified" : a.verification ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
