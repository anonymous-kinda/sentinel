import type { PassWindow } from "../../api/types";
import { dtg } from "../../lib/format";
import { WINDOW_KIND_LABEL, windowKind } from "../../lib/passes";

/** The pass under the pointer or keyboard focus: its timing, geometry and
 *  how old the element set behind it is. */
export function WindowDetail({ window: w }: { window: PassWindow | null }) {
  return (
    <div className="gantt-detail" aria-live="polite">
      {w ? (
        <>
          <div className="gantt-detail-head">
            <b>{w.name}</b>
            <span className="chip">{w.sensor}</span>
            <span>{WINDOW_KIND_LABEL[windowKind(w)]}</span>
            {w.stale && <span className="chip chip-stale">STALE</span>}
          </div>
          <dl className="gantt-detail-facts">
            <Fact term="rise" value={dtg(w.rise)} />
            <Fact term="culmination" value={dtg(w.culmination)} />
            <Fact term="set" value={dtg(w.set)} />
            <Fact term="max elevation" value={`${w.max_elevation_deg.toFixed(1)}°`} />
            <Fact term="mask (field of regard)" value={`${w.mask_elevation_deg.toFixed(1)}°`} />
            <Fact term="element age" value={`${w.element_age_days.toFixed(1)} d`} />
            <Fact term="timing pad" value={`±${Math.round(w.pad_s)} s`} />
          </dl>
        </>
      ) : (
        <span className="muted">Hover or focus a pass for its rise, culmination and set.</span>
      )}
    </div>
  );
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div>
      <dt>{term}</dt>
      <dd>{value}</dd>
    </div>
  );
}
