import type { DilutionCurve as Curve } from "../api/types";
import { sciPlain, sci } from "../lib/format";

/** Interpolate log10 Pc at log10 k from the engine's samples. */
export function interpolatePc(curve: Curve, log10k: number): number | null {
  const xs = curve.log10_k ?? [];
  const ys = curve.pc ?? [];
  if (xs.length < 2) return null;
  if (log10k <= xs[0]) return ys[0];
  if (log10k >= xs[xs.length - 1]) return ys[ys.length - 1];
  let i = 1;
  while (xs[i] < log10k) i++;
  const t = (log10k - xs[i - 1]) / (xs[i] - xs[i - 1]);
  const a = ys[i - 1];
  const b = ys[i];
  if (a <= 0 || b <= 0) return a + t * (b - a);
  return Math.pow(10, Math.log10(a) + t * (Math.log10(b) - Math.log10(a)));
}

/**
 * Pc as a function of covariance scale k (log-log), from the same
 * integrator the engine uses. The operating point is k = 1. Right of the
 * peak k* lies the dilution region: there, more uncertainty lowers Pc, so
 * a low number may reflect ignorance rather than safety.
 */
export function DilutionCurve({
  curve,
  log10k,
  onChange,
}: {
  curve: Curve;
  log10k: number;
  onChange: (v: number) => void;
}) {
  if (!curve.log10_k || !curve.pc || curve.k_star === undefined || curve.pc_max === undefined) {
    return <div className="plot-empty">No Pc curve: the engine refused this event, or there is no covariance.</div>;
  }
  const W = 320;
  const H = 200;
  const pad = { l: 44, r: 10, t: 14, b: 30 };
  const xs = curve.log10_k;
  const floor = Math.max(curve.pc_max * 1e-10, 1e-300);
  const ys = curve.pc.map((p) => Math.log10(Math.max(p, floor)));
  const yMax = Math.log10(curve.pc_max) + 0.3;
  const yMin = Math.max(Math.min(...ys), Math.log10(curve.pc_max) - 8);
  const x0 = xs[0];
  const x1 = xs[xs.length - 1];
  const X = (v: number) => pad.l + ((v - x0) / (x1 - x0)) * (W - pad.l - pad.r);
  const Y = (v: number) => pad.t + (1 - (Math.max(v, yMin) - yMin) / (yMax - yMin)) * (H - pad.t - pad.b);

  const path = xs.map((x, i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(ys[i]).toFixed(1)}`).join("");
  const lkStar = Math.log10(curve.k_star);
  const pcAtSlider = interpolatePc(curve, log10k);
  const operatingY = Math.log10(Math.max(curve.pc_at_k1 ?? floor, floor));

  const ticksX = [];
  for (let t = Math.ceil(x0); t <= Math.floor(x1); t++) ticksX.push(t);
  const ticksY = [];
  for (let t = Math.ceil(yMin); t <= Math.floor(yMax); t += Math.max(1, Math.round((yMax - yMin) / 4))) ticksY.push(t);

  return (
    <figure className="plot">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Collision probability versus covariance scale factor">
        <rect x="0" y="0" width={W} height={H} className="plot-bg" />
        <rect x={X(lkStar)} y={pad.t} width={X(x1) - X(lkStar)} height={H - pad.t - pad.b} className="dilution-region" />
        <text x={X(x1) - 4} y={H - pad.b - 6} className="plot-label plot-label-dil" textAnchor="end">
          dilution region →
        </text>
        {ticksX.map((t) => (
          <g key={`x${t}`}>
            <line x1={X(t)} y1={H - pad.b} x2={X(t)} y2={H - pad.b + 3} className="axis" />
            <text x={X(t)} y={H - pad.b + 13} className="tick" textAnchor="middle">
              {t === 0 ? "1" : `1e${t}`}
            </text>
          </g>
        ))}
        {ticksY.map((t) => (
          <g key={`y${t}`}>
            <line x1={pad.l - 3} y1={Y(t)} x2={W - pad.r} y2={Y(t)} className="axis-faint" />
            <text x={pad.l - 5} y={Y(t) + 3} className="tick" textAnchor="end">
              1e{t}
            </text>
          </g>
        ))}
        <line x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} className="axis" />
        <path d={path} className="curve" />
        <line x1={X(0)} y1={pad.t} x2={X(0)} y2={H - pad.b} className="operating-line" />
        <circle cx={X(0)} cy={Y(operatingY)} r={4} className="operating-dot" />
        <circle cx={X(lkStar)} cy={Y(Math.log10(curve.pc_max))} r={4} className="peak-dot" />
        <line x1={X(log10k)} y1={pad.t} x2={X(log10k)} y2={H - pad.b} className="slider-line" />
        <text x={W / 2} y={H - 4} className="tick" textAnchor="middle">
          covariance scale k (operating point k = 1)
        </text>
      </svg>
      <input
        className="k-slider"
        type="range"
        min={x0}
        max={x1}
        step={(x1 - x0) / 400}
        value={log10k}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label="Covariance scale factor, log10"
      />
      <figcaption>
        <span className="legend-op">●</span> k=1 Pc {curve.pc_at_k1 !== undefined ? sci(curve.pc_at_k1) : "-"} ·{" "}
        <span className="legend-peak">●</span> peak k*={curve.k_star.toPrecision(3)} Pc {sci(curve.pc_max)}
        {pcAtSlider !== null && (
          <>
            {" "}· slider Pc≈{sciPlain(pcAtSlider)} <span className="muted">(interpolated)</span>
          </>
        )}
      </figcaption>
    </figure>
  );
}
