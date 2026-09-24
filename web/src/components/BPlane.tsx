import type { Encounter } from "../api/types";
import { metres } from "../lib/format";

/**
 * The encounter plane, seen along the relative velocity.
 *
 * The hard-body disk sits at the origin (the primary). The combined
 * uncertainty ellipse is centred on the secondary's projected position.
 * Collision probability is the share of that Gaussian lying on the disk.
 *
 * The covariance scale k comes from the shared slider: at small k the
 * ellipse is tight and misses the disk; near k* it covers the disk best;
 * at large k it smears so thin that little mass lands on the disk. That is
 * the dilution pathology, drawn.
 */
export function BPlane({ encounter, log10k }: { encounter: Encounter; log10k: number }) {
  if (!encounter.available || !encounter.mu_m || !encounter.sigma_major_m || !encounter.sigma_minor_m) {
    return <div className="plot-empty">No encounter plane: {encounter.reason ?? "no covariance"}</div>;
  }
  const W = 320;
  const H = 240;
  const k = Math.pow(10, log10k);
  const s = Math.sqrt(k);
  const [mx, my] = encounter.mu_m;
  const a1 = encounter.sigma_major_m;
  const b1 = encounter.sigma_minor_m;
  const angle = ((encounter.major_axis_angle_rad ?? 0) * 180) / Math.PI;
  const hbr = encounter.hbr_m ?? 0;

  // Fixed extent from the operating point (k = 1), so growth is visible.
  const kRef = Math.max(1, encounter.k_star ?? 1);
  const extent = Math.max(Math.hypot(mx, my), 3 * a1 * Math.sqrt(kRef), hbr * 4) * 1.25;
  const px = Math.min(W, H) / 2 / extent;
  const cx = W / 2;
  const cy = H / 2;

  const diskPx = hbr * px;
  const diskShown = Math.max(diskPx, 3.5);
  // Density at the ellipse centre falls as 1/k; show it as fill opacity.
  const fill = Math.max(0.04, Math.min(0.55, 0.55 / k));

  return (
    <figure className="plot">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Encounter plane with uncertainty ellipses and hard-body disk">
        <defs>
          <clipPath id="bplane-clip">
            <rect x="0" y="0" width={W} height={H} />
          </clipPath>
        </defs>
        <rect x="0" y="0" width={W} height={H} className="plot-bg" />
        <line x1={0} y1={cy} x2={W} y2={cy} className="axis-faint" />
        <line x1={cx} y1={0} x2={cx} y2={H} className="axis-faint" />
        <g clipPath="url(#bplane-clip)">
          <g transform={`translate(${cx + mx * px} ${cy - my * px}) rotate(${-angle})`}>
            <ellipse rx={a1 * s * px} ry={b1 * s * px} className="ellipse ellipse-1" style={{ fillOpacity: fill }} />
            <ellipse rx={2 * a1 * s * px} ry={2 * b1 * s * px} className="ellipse ellipse-2" />
            <ellipse rx={3 * a1 * s * px} ry={3 * b1 * s * px} className="ellipse ellipse-3" />
          </g>
          <line x1={cx} y1={cy} x2={cx + mx * px} y2={cy - my * px} className="miss-vector" />
          <circle cx={cx + mx * px} cy={cy - my * px} r={2.5} className="secondary-dot" />
        </g>
        <circle cx={cx} cy={cy} r={diskShown} className="hbr-disk" />
        {diskPx < 3.5 && <circle cx={cx} cy={cy} r={9} className="hbr-ring" />}
        <text x={8} y={16} className="plot-label">
          encounter plane · k = {k < 0.01 || k > 999 ? k.toExponential(1) : k.toFixed(k < 1 ? 3 : 2)}
        </text>
        <text x={8} y={H - 8} className="plot-label">
          miss {metres(Math.hypot(mx, my))} · 1σ {metres(a1 * s)} × {metres(b1 * s)}
        </text>
        <text x={W - 8} y={16} className="plot-label plot-label-disk" textAnchor="end">
          ● HBR {metres(hbr)}
          {diskPx < 3.5 ? " (enlarged)" : ""}
        </text>
      </svg>
      <figcaption>
        Uncertainty ellipses (1σ/2σ/3σ) around the secondary; the disk is the combined hard body at the primary.
      </figcaption>
    </figure>
  );
}
