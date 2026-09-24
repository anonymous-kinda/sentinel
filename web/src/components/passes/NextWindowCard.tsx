import type { PassesView, SkippedImager, UnobservedGap } from "../../api/types";
import { countdown, dtg, duration } from "../../lib/format";
import { intervalHours, meetsReactionTime } from "../../lib/passes";

/**
 * The headline: the next stretch of time, at least the unit's reaction time
 * long, that no catalogued imager observes. It is not an all-clear, and the
 * card says when its inputs were stale or incomplete.
 */
export function NextWindowCard({ view, nowMs }: { view: PassesView; nowMs: number }) {
  const reaction = view.unit.reaction_time_min;
  const next = view.next_unobserved;
  return (
    <section className="card next-window" aria-label="Next unobserved window">
      <h3 className="passes-head">Next unobserved window</h3>
      <p className="muted small">
        {view.label}, at least {reaction} min
      </p>
      {next ? (
        <>
          <WindowFacts gap={next} reactionMin={reaction} nowMs={nowMs} />
          <ConfidenceWarnings gap={next} skipped={view.catalog.skipped} />
        </>
      ) : (
        <p className="next-none">
          No unobserved window of {reaction} min in the next {intervalHours(view)} h
        </p>
      )}
    </section>
  );
}

function WindowFacts({ gap, reactionMin, nowMs }: { gap: UnobservedGap; reactionMin: number; nowMs: number }) {
  const startMs = Date.parse(gap.start);
  const timing =
    startMs > nowMs
      ? `opens ${countdown((startMs - nowMs) / 1000)}`
      : `open now, closes ${countdown((Date.parse(gap.end) - nowMs) / 1000)}`;
  const meets = meetsReactionTime(gap, reactionMin, nowMs);
  return (
    <>
      <div className="next-when">
        <span className="next-dtg">{dtg(gap.start)}</span>
        <span className="muted">to</span>
        <span className="next-dtg">{dtg(gap.end)}</span>
      </div>
      <dl className="next-facts">
        <div>
          <dt>duration</dt>
          <dd>{duration(gap.duration_s)}</dd>
        </div>
        <div>
          <dt>starts</dt>
          <dd>{timing}</dd>
        </div>
        <div>
          <dt>reaction time</dt>
          <dd className={meets ? "good" : "warn"}>
            {meets ? `meets the ${reactionMin} min reaction time` : `shorter than the ${reactionMin} min reaction time`}
          </dd>
        </div>
      </dl>
    </>
  );
}

function ConfidenceWarnings({ gap, skipped }: { gap: UnobservedGap; skipped: SkippedImager[] }) {
  const n = skipped.length;
  return (
    <>
      {gap.low_confidence && (
        <div className="answer-note warn" role="note">
          Low confidence: an element set older than 3 days bounds or overlaps this window, so its edges may be off by
          more than the timing pad.
        </div>
      )}
      {n > 0 && (
        <div className="answer-note warn" role="note">
          Low confidence: {n} catalogued imager{n === 1 ? "" : "s"} skipped (no usable element set). Skipped passes are
          not counted, so this window may be shorter than shown.
        </div>
      )}
    </>
  );
}
