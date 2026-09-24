import { useState, type ReactNode } from "react";
import type { NodeInfo, PassCatalog, PassUnit, PassesView } from "../../api/types";
import { deleteJSON, putJSON, useResource } from "../../api/client";
import { log } from "../../lib/log";
import { ImagerCatalog } from "./ImagerCatalog";
import { NextWindowCard } from "./NextWindowCard";
import { PassGantt } from "./PassGantt";
import { UnitForm } from "./UnitForm";

/**
 * The Passes tab: when catalogued public imagers can observe the unit, and
 * the stretches between. Everything is computed on this node from public
 * element sets and imaging assumptions (docs/icd/passes-api.md); the unit's
 * position never leaves it. The tab states what the model leaves out in a
 * footer that is always on screen, whatever else fails.
 */

const HOURS = 24;
const UNIT_PATH = "/api/passes/unit";
const PASSES_PATH = `/api/passes?hours=${HOURS}`;
const CATALOG_PATH = "/api/passes/catalog";

export const HONESTY_NOTE =
  "Catalogued public imagers only. Uncatalogued and non-public sensors are outside this model. Fields of regard are " +
  "planning assumptions; element sets carry kilometre-level error, covered by the timing pad.";

interface Props {
  node: NodeInfo | null;
  version: number;
  nowMs: number;
}

export function PassesPanel({ node, version, nowMs }: Props) {
  // Our own edits refetch at once; SSE events arrive through `version`.
  const [edits, setEdits] = useState(0);
  const refresh = () => setEdits((n) => n + 1);
  const v = version + edits;
  const unitRes = useResource<PassUnit>(UNIT_PATH, v);
  const passesRes = useResource<PassesView>(PASSES_PATH, v);
  const catalogRes = useResource<PassCatalog>(CATALOG_PATH, v);

  const noUnit = passesRes.status === 409;
  const view = noUnit ? null : passesRes.data;
  const errors = [
    passesRes.error && !noUnit && `Pass windows unavailable: ${passesRes.error}.${view ? " Showing the last good result." : ""}`,
    unitRes.error && unitRes.status !== 404 && `Unit unavailable: ${unitRes.error}.`,
    catalogRes.error && `Imaging catalog unavailable: ${catalogRes.error}.`,
  ].filter((e): e is string => Boolean(e));

  async function save(unit: PassUnit) {
    await putJSON(UNIT_PATH, unit);
    log.info({ unit_id: unit.unit_id }, "Pass unit saved");
    refresh();
  }

  async function remove() {
    await deleteJSON(UNIT_PATH);
    log.info({}, "Pass unit deleted");
    refresh();
  }

  return (
    <div className="passes">
      <p className="lede">
        When catalogued public imagers can observe the unit, and the time between. Computed on this node from public
        element sets and each imager's field of regard; the unit's position never leaves it.
      </p>
      {errors.map((e) => (
        <div className="answer-note bad passes-error" role="alert" key={e}>
          {e}
        </div>
      ))}
      <div className="passes-top">
        <Headline view={view} noUnit={noUnit} failed={passesRes.error !== null} nowMs={nowMs} />
        {unitRes.data !== null || unitRes.error !== null ? (
          <UnitForm
            unit={unitRes.status === 404 ? null : unitRes.data}
            readOnly={node?.read_only ?? true}
            onSave={save}
            onDelete={remove}
          />
        ) : (
          <Placeholder title="Unit">Loading…</Placeholder>
        )}
      </div>
      {view && (
        <section className="passes-timeline" aria-label="Pass timeline">
          <h3 className="passes-head">Next {HOURS} h</h3>
          <PassesMeta view={view} />
          <PassGantt view={view} nowMs={nowMs} />
        </section>
      )}
      {catalogRes.data && <ImagerCatalog catalog={catalogRes.data} />}
      <footer className="passes-honesty">{HONESTY_NOTE}</footer>
    </div>
  );
}

function Headline({ view, noUnit, failed, nowMs }: { view: PassesView | null; noUnit: boolean; failed: boolean; nowMs: number }) {
  if (view) return <NextWindowCard view={view} nowMs={nowMs} />;
  const title = "Next unobserved window";
  if (noUnit) {
    return (
      <Placeholder title={title}>
        No pass windows yet: set the unit's position to see when catalogued imagers can observe it.
      </Placeholder>
    );
  }
  return <Placeholder title={title}>{failed ? "No pass windows to show." : "Loading…"}</Placeholder>;
}

function Placeholder({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card" aria-label={title}>
      <h3 className="passes-head">{title}</h3>
      <p className="muted">{children}</p>
    </section>
  );
}

/** Where the numbers came from: the provider and the element sets' ages. */
function PassesMeta({ view }: { view: PassesView }) {
  const { oldest_age_days: oldest, newest_age_days: newest, stale } = view.elements;
  const ages = oldest !== null && newest !== null ? `element sets ${newest.toFixed(1)} to ${oldest.toFixed(1)} d old` : "element set ages unknown";
  return (
    <p className="muted small passes-meta">
      provider {view.provider} · {view.catalog.imagers} catalogued imagers · {ages}
      {stale > 0 ? ` · ${stale} stale` : ""}
    </p>
  );
}
