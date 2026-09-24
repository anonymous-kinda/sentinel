import type { Validation } from "../api/types";
import { useResource } from "../api/client";
import { sciPlain } from "../lib/format";
import { Pending } from "./Pending";

function Scatter({ rows }: { rows: NonNullable<Validation["rows"]> }) {
  const W = 360;
  const H = 300;
  const pad = 40;
  const vals = rows.flatMap((r) => [r.sentinel_pc, r.cara_pc2d]).filter((v) => v > 0);
  const lo = Math.max(Math.floor(Math.log10(Math.min(...vals))), -30);
  const hi = Math.ceil(Math.log10(Math.max(...vals)));
  const P = (v: number) => (Math.max(Math.log10(Math.max(v, 1e-300)), lo) - lo) / (hi - lo);
  const X = (v: number) => pad + P(v) * (W - pad - 10);
  const Y = (v: number) => H - pad - P(v) * (H - pad - 10);
  const ticks = [];
  for (let t = lo; t <= hi; t += Math.max(1, Math.round((hi - lo) / 5))) ticks.push(t);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="scatter" role="img" aria-label="Sentinel Pc against CARA Pc2D">
      <rect x={0} y={0} width={W} height={H} className="plot-bg" />
      <line x1={X(10 ** lo)} y1={Y(10 ** lo)} x2={X(10 ** hi)} y2={Y(10 ** hi)} className="diag" />
      {ticks.map((t) => (
        <g key={t}>
          <text x={X(10 ** t)} y={H - pad + 14} className="tick" textAnchor="middle">
            1e{t}
          </text>
          <text x={pad - 5} y={Y(10 ** t) + 3} className="tick" textAnchor="end">
            1e{t}
          </text>
        </g>
      ))}
      {rows.map((r) => (
        <circle
          key={r.case_id}
          cx={X(r.cara_pc2d)}
          cy={Y(r.sentinel_pc)}
          r={3.5}
          className={r.cara_says_2d_valid ? "pt-valid" : "pt-invalid"}
        >
          <title>
            {r.primary} × {r.secondary}: Sentinel {sciPlain(r.sentinel_pc, 6)} vs CARA {sciPlain(r.cara_pc2d, 6)} (rel{" "}
            {r.rel_error.toExponential(1)})
          </title>
        </circle>
      ))}
      <text x={W / 2} y={H - 6} className="tick" textAnchor="middle">
        NASA CARA published Pc2D (values below 1e{lo} drawn at the floor)
      </text>
      <text x={12} y={H / 2} className="tick" textAnchor="middle" transform={`rotate(-90 12 ${H / 2})`}>
        Sentinel Pc (gate off)
      </text>
    </svg>
  );
}

export function ValidationPanel() {
  const { data, error } = useResource<Validation>("/api/validation");
  if (!data) return <Pending what="NASA comparison" error={error} loading="Running the NASA comparison on this node…" />;
  if (!data.available || !data.rows || !data.confusion) {
    return <div className="empty">Validation data not bundled with this node. {data.reason}</div>;
  }
  const c = data.confusion;
  const rows = [...data.rows].sort((a, b) => Number(a.cara_says_2d_valid) - Number(b.cara_says_2d_valid));
  return (
    <div className="validation">
      <p className="lede">
        This node just re-ran NASA CARA's published operational test set through its own CDM parser and engine. These
        are real conjunctions (HST, TERRA, SWIFT, …) with CARA's published 2D Pc, 3D Nc and its verdict on whether the 2D
        method applies. The same comparison runs in CI (Tier 3) and in <code>docs/validation-report.md</code>.
      </p>
      <div className="cards">
        <div className="card">
          <span className="card-k">operational events</span>
          <span className="card-v">{data.operational_count}</span>
        </div>
        <div className="card">
          <span className="card-k">worst relative error vs CARA</span>
          <span className="card-v">{data.worst_rel_error?.toExponential(1)}</span>
        </div>
        <div className="card">
          <span className="card-k">2D Pc returned where CARA says 2D is invalid</span>
          <span className={`card-v ${c.fn === 0 ? "good" : "bad"}`}>{c.fn}</span>
        </div>
        <div className="card">
          <span className="card-k">Alfano benchmark, worst rel. error</span>
          <span className="card-v">{data.alfano_worst_rel_error?.toExponential(1)}</span>
        </div>
      </div>
      <div className="validation-grid">
        <Scatter rows={data.rows} />
        <div>
          <table className="confusion">
            <thead>
              <tr>
                <th />
                <th>CARA: 2D invalid</th>
                <th>CARA: 2D valid</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th>Sentinel refuses</th>
                <td className="good">{c.tp}</td>
                <td>{c.fp}</td>
              </tr>
              <tr>
                <th>Sentinel returns a Pc</th>
                <td className={c.fn === 0 ? "good" : "bad"}>{c.fn}</td>
                <td className="good">{c.tn}</td>
              </tr>
            </tbody>
          </table>
          <p className="note">{data.calibration_note} False positives are conservative: Sentinel withholds a number, it never states a wrong one.</p>
          <p className="note muted">{data.source}</p>
        </div>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>primary</th>
            <th>secondary</th>
            <th>rel. speed</th>
            <th>Sentinel Pc</th>
            <th>CARA Pc2D</th>
            <th>rel. error</th>
            <th>CARA 3D Nc</th>
            <th>CARA: 2D valid?</th>
            <th>Sentinel default</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.case_id}>
              <td>{r.primary}</td>
              <td>{r.secondary}</td>
              <td className="num">{r.relative_speed_m_s.toFixed(0)} m/s</td>
              <td className="num">{sciPlain(r.sentinel_pc, 4)}</td>
              <td className="num">{sciPlain(r.cara_pc2d, 4)}</td>
              <td className="num">{r.rel_error.toExponential(1)}</td>
              <td className="num">{sciPlain(r.cara_nc3d, 3)}</td>
              <td className={r.cara_says_2d_valid ? "" : "warn"}>{r.cara_says_2d_valid ? "yes" : "no"}</td>
              <td className={r.sentinel_default === "REFUSED" ? "refused" : ""}>
                {r.sentinel_default === "REFUSED" ? `refused · ${r.refusal_reason}` : "Pc"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
