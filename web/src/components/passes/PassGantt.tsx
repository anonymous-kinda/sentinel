import { useId, useState } from "react";
import type { PassWindow, PassesView, UnobservedGap } from "../../api/types";
import { dtg, duration } from "../../lib/format";
import { WINDOW_KIND_LABEL, passKey, windowKind } from "../../lib/passes";
import {
  ganttLayout,
  hourTicks,
  imagerRows,
  labelEvery,
  timeScale,
  zuluHour,
  type GanttLayout,
  type ImagerRow,
} from "../../lib/timeline";
import { useElementWidth } from "../../lib/useElementWidth";
import { GanttLegend } from "./GanttLegend";
import { WindowDetail } from "./WindowDetail";

/**
 * Every catalogued imager's passes over the unit across the interval, one
 * row per imager, with the gaps between usable passes in a band on top.
 * The server computed all of it; this only draws it. Each pass is focusable
 * and shows its timing, geometry and element age on focus or hover.
 */

const FALLBACK_WIDTH = 960;
const CHAR_PX = 6.3; // 10px monospace, for labels inside gaps
const NAME_CHAR_PX = 7; // 11px sans, upper-case imager names
const HIT_MIN_PX = 16;

type Scale = (t: number) => number;
const ms = Date.parse;

export function PassGantt({ view, nowMs }: { view: PassesView; nowMs: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(FALLBACK_WIDTH);
  // By key, not by object: a refetch replaces the objects, and the details
  // must show the pass as the server now reports it.
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const active = view.windows.find((w) => passKey(w) === activeKey) ?? null;
  const setActive = (w: PassWindow) => setActiveKey(passKey(w));
  const hatchId = `hatch-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const rows = imagerRows(view.windows);
  const layout = ganttLayout(rows.length, width);
  const x = timeScale(ms(view.start), ms(view.end), layout.plotX0, layout.plotX1);

  return (
    <figure className="gantt">
      <div ref={ref} className="gantt-frame">
        <svg
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          role="group"
          aria-label={`Imaging passes over the unit, ${dtg(view.start)} to ${dtg(view.end)}`}
        >
          <defs>
            <pattern id={hatchId} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="5" className="hatch-line" />
            </pattern>
          </defs>
          <TimeAxis view={view} layout={layout} x={x} />
          <text className="plot-label gantt-caption" x={4} y={layout.bandY - 5}>
            {view.label}
          </text>
          {view.gaps.map((gap) => (
            <GapMark key={gap.start} gap={gap} label={view.label} layout={layout} x={x} hatch={hatchId} />
          ))}
          {rows.map((row, i) => (
            <ImagerRowMarks key={row.norad_id} row={row} y={layout.rowY(i)} layout={layout} x={x} hatch={hatchId} onActive={setActive} active={active} />
          ))}
          <NowLine view={view} nowMs={nowMs} layout={layout} x={x} />
        </svg>
      </div>
      {rows.length === 0 && <p className="muted">No catalogued imager passes over the unit in this interval.</p>}
      <WindowDetail window={active} />
      <GanttLegend label={view.label} hatch={hatchId} />
    </figure>
  );
}

function TimeAxis({ view, layout, x }: { view: PassesView; layout: GanttLayout; x: Scale }) {
  const ticks = hourTicks(ms(view.start), ms(view.end));
  const every = labelEvery((layout.plotX1 - layout.plotX0) / Math.max(ticks.length, 1));
  return (
    <g className="gantt-axis">
      {ticks.map((t) => (
        <g key={t}>
          <line className="axis-faint" x1={x(t)} x2={x(t)} y1={layout.bandY} y2={layout.axisY} />
          {new Date(t).getUTCHours() % every === 0 && (
            <text className="tick" x={x(t)} y={layout.axisY + 13} textAnchor="middle">
              {zuluHour(t)}
            </text>
          )}
        </g>
      ))}
      <line className="axis" x1={layout.plotX0} x2={layout.plotX1} y1={layout.axisY} y2={layout.axisY} />
    </g>
  );
}

function GapMark({ gap, label, layout, x, hatch }: { gap: UnobservedGap; label: string; layout: GanttLayout; x: Scale; hatch: string }) {
  const x0 = x(ms(gap.start));
  const w = x(ms(gap.end)) - x0;
  const length = duration(gap.duration_s);
  const confidence = gap.low_confidence ? ", low confidence (stale element set)" : "";
  return (
    <g role="img" aria-label={`${label}: ${dtg(gap.start)} to ${dtg(gap.end)}, ${length}${confidence}`}>
      <rect className="gap" x={x0} y={layout.bandY} width={w} height={layout.bandH} />
      {gap.low_confidence && <rect className="hatch hatch-soft" x={x0} y={layout.bandY} width={w} height={layout.bandH} fill={`url(#${hatch})`} />}
      {w >= length.length * CHAR_PX + 8 && (
        <text className="gap-text" x={x0 + w / 2} y={layout.bandY + layout.bandH / 2 + 4} textAnchor="middle" aria-hidden="true">
          {length}
        </text>
      )}
    </g>
  );
}

function ImagerRowMarks({
  row,
  y,
  layout,
  x,
  hatch,
  active,
  onActive,
}: {
  row: ImagerRow;
  y: number;
  layout: GanttLayout;
  x: Scale;
  hatch: string;
  active: PassWindow | null;
  onActive: (w: PassWindow) => void;
}) {
  const chipX = layout.plotX0 - 36;
  const maxChars = Math.floor((chipX - 12) / NAME_CHAR_PX);
  const name = row.name.length > maxChars ? `${row.name.slice(0, Math.max(maxChars - 1, 1))}…` : row.name;
  return (
    <g className="gantt-row">
      <g className="gantt-row-label">
        <title>{row.name}</title>
        <text className="gantt-row-name" x={4} y={y + layout.rowH / 2 + 4}>
          {name}
        </text>
      </g>
      <rect className={`gantt-chip gantt-chip-${row.sensor.toLowerCase()}`} x={chipX} y={y + 5} width={30} height={layout.rowH - 10} rx={3} />
      <text className="gantt-chip-text" x={chipX + 15} y={y + layout.rowH / 2 + 3.5} textAnchor="middle">
        {row.sensor}
      </text>
      {row.windows.map((w) => (
        <WindowMark key={passKey(w)} w={w} y={y} h={layout.rowH} x={x} hatch={hatch} active={w === active} onActive={onActive} />
      ))}
    </g>
  );
}

function WindowMark({
  w,
  y,
  h,
  x,
  hatch,
  active,
  onActive,
}: {
  w: PassWindow;
  y: number;
  h: number;
  x: Scale;
  hatch: string;
  active: boolean;
  onActive: (w: PassWindow) => void;
}) {
  const kind = windowKind(w);
  const pad0 = x(ms(w.padded_start));
  const pad1 = x(ms(w.padded_end));
  const core0 = x(ms(w.rise));
  const core1 = x(ms(w.set));
  const centre = (core0 + core1) / 2;
  const hit0 = Math.min(pad0, centre - HIT_MIN_PX / 2);
  const hit1 = Math.max(pad1, centre + HIT_MIN_PX / 2);
  const stale = w.stale ? ", element set stale" : "";
  const label = `${w.name}: ${WINDOW_KIND_LABEL[kind]}${stale}, rise ${dtg(w.rise)}, set ${dtg(w.set)}, max elevation ${w.max_elevation_deg.toFixed(1)}°`;
  const show = () => onActive(w);
  return (
    <g
      className={`win win-${kind}${active ? " win-active" : ""}`}
      data-kind={kind}
      tabIndex={0}
      role="img"
      aria-label={label}
      onFocus={show}
      onMouseEnter={show}
    >
      <rect className="win-hit" x={hit0} y={y} width={hit1 - hit0} height={h} />
      <rect className="win-pad" x={pad0} y={y + 5} width={pad1 - pad0} height={h - 10} />
      <rect className="win-core" x={core0} y={y + 5} width={Math.max(core1 - core0, 1.5)} height={h - 10} />
      {w.stale && <rect className="hatch" x={pad0} y={y + 5} width={pad1 - pad0} height={h - 10} fill={`url(#${hatch})`} />}
    </g>
  );
}

function NowLine({ view, nowMs, layout, x }: { view: PassesView; nowMs: number; layout: GanttLayout; x: Scale }) {
  if (nowMs < ms(view.start) || nowMs > ms(view.end)) return null;
  const nx = x(nowMs);
  return (
    <g className="gantt-now" aria-hidden="true">
      <line className="now-line" x1={nx} x2={nx} y1={layout.bandY - 2} y2={layout.axisY} />
      <text className="now-label" x={nx} y={layout.axisY + 27} textAnchor="middle">
        now
      </text>
    </g>
  );
}
