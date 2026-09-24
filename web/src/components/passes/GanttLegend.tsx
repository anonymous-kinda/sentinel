import type { ReactNode } from "react";
import { WINDOW_KIND_LABEL, type WindowKind } from "../../lib/passes";

/** Every mark on the timeline, named in words: no meaning is carried by
 *  colour alone. Swatches reuse the timeline's own classes. */
export function GanttLegend({ label, hatch }: { label: string; hatch: string }) {
  const kinds = Object.keys(WINDOW_KIND_LABEL) as WindowKind[];
  return (
    <figcaption>
      <ul className="gantt-legend" aria-label="Legend">
        {kinds.map((kind) => (
          <Item key={kind} text={WINDOW_KIND_LABEL[kind]}>
            <g className={`win win-${kind}`}>
              <rect className="win-core" x={4} y={2} width={14} height={8} />
            </g>
          </Item>
        ))}
        <Item text="lighter ends: timing pad for element-set error">
          <g className="win win-eo">
            <rect className="win-pad" x={0} y={2} width={22} height={8} />
            <rect className="win-core" x={6} y={2} width={10} height={8} />
          </g>
        </Item>
        <Item text="hatched: element set older than 3 days">
          <rect className="win-core legend-plain" x={4} y={2} width={14} height={8} />
          <rect className="hatch" x={4} y={2} width={14} height={8} fill={`url(#${hatch})`} />
        </Item>
        <Item text={label}>
          <rect className="gap" x={0} y={1} width={22} height={10} />
        </Item>
        <Item text="now (node clock)">
          <line className="now-line" x1={11} x2={11} y1={0} y2={12} />
        </Item>
      </ul>
    </figcaption>
  );
}

function Item({ text, children }: { text: string; children: ReactNode }) {
  return (
    <li>
      <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true">
        {children}
      </svg>
      <span>{text}</span>
    </li>
  );
}
