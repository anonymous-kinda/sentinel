import type { HistoryEntry } from "../api/types";
import { sciPlain } from "../lib/format";

/**
 * Pc and worst-case Pc across the CDM updates for one event. Operators
 * receive a sequence, not a message; the trend is the information. A
 * refused update is drawn as a gap with a cross - never as zero.
 */
export function HistorySpark({ history }: { history: HistoryEntry[] }) {
  const W = 320;
  const H = 96;
  const pad = { l: 40, r: 8, t: 10, b: 18 };
  const pcs = history.map((h) => h.assessment.pc);
  const maxes = history.map((h) => h.assessment.pc_max);
  const positive = [...pcs, ...maxes].filter((v): v is number => v !== null && v > 0);
  if (positive.length === 0) {
    return <div className="plot-empty">No Pc in any update: every CDM for this event was refused.</div>;
  }
  const yMax = Math.log10(Math.max(...positive)) + 0.3;
  const yMin = Math.max(Math.log10(Math.min(...positive)) - 0.3, yMax - 12);
  const n = history.length;
  const X = (i: number) => pad.l + (n === 1 ? 0.5 : i / (n - 1)) * (W - pad.l - pad.r);
  const Y = (v: number) => pad.t + (1 - (Math.max(Math.log10(v), yMin) - yMin) / (yMax - yMin)) * (H - pad.t - pad.b);

  const line = (values: (number | null)[]) =>
    values
      .map((v, i) => (v !== null && v > 0 ? `${i && values[i - 1] !== null ? "L" : "M"}${X(i)},${Y(v)}` : ""))
      .join("");

  return (
    <figure className="plot">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Pc across CDM updates">
        <rect x="0" y="0" width={W} height={H} className="plot-bg" />
        <path d={line(maxes)} className="spark-max" />
        <path d={line(pcs)} className="spark-pc" />
        {history.map((h, i) => {
          const a = h.assessment;
          if (a.method === "REFUSED" || a.pc === null) {
            return (
              <text key={h.sha256} x={X(i)} y={H / 2} className="spark-refused" textAnchor="middle">
                ×
              </text>
            );
          }
          return (
            <circle
              key={h.sha256}
              cx={X(i)}
              cy={Y(Math.max(a.pc, 10 ** yMin))}
              r={3.5}
              className={a.dilution_flag ? "spark-dot spark-dot-diluted" : "spark-dot"}
            >
              <title>
                {h.message_id}: Pc {sciPlain(a.pc)}
                {a.dilution_flag ? ` (diluted; worst ${sciPlain(a.pc_max ?? 0)})` : ""}
              </title>
            </circle>
          );
        })}
        <text x={pad.l - 4} y={pad.t + 8} className="tick" textAnchor="end">
          1e{Math.floor(yMax)}
        </text>
        <text x={pad.l - 4} y={H - pad.b} className="tick" textAnchor="end">
          1e{Math.ceil(yMin)}
        </text>
        <text x={W - pad.r} y={H - 4} className="tick" textAnchor="end">
          CDM update →
        </text>
      </svg>
      <figcaption>
        <span className="legend-pc">—</span> Pc <span className="legend-max">- -</span> worst case{" "}
        <span className="legend-dil">●</span> diluted update
      </figcaption>
    </figure>
  );
}
