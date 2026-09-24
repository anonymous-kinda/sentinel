import { useCallback, useEffect, useMemo, useState } from "react";
import type { EventSummary, NodeInfo, Trajectory } from "./api/types";
import { useResource, useStream, type StreamEvent } from "./api/client";
import { EventList } from "./components/EventList";
import { EventDetail } from "./components/EventDetail";
import { Globe } from "./components/Globe";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ValidationPanel } from "./components/ValidationPanel";
import { sciPlain } from "./lib/format";
import { extensionTabs, type ExtensionContext } from "./extensions";

type Tab = "ops" | "library" | "validation" | string;

interface Activity {
  at: number;
  text: string;
  tone: "info" | "warn" | "bad";
}

function useNodeClock(node: NodeInfo | null): number {
  const [offset, setOffset] = useState(0);
  const [, setTick] = useState(0);
  useEffect(() => {
    if (node) setOffset(Date.parse(node.now) - Date.now());
  }, [node]);
  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  return Date.now() + offset;
}

function zulu(ms: number): string {
  return new Date(ms).toISOString().slice(11, 19) + "Z";
}

export default function App() {
  const [version, setVersion] = useState(0);
  const { data: node } = useResource<NodeInfo>("/api/node", version);
  const nowMs = useNodeClock(node);
  const [tab, setTab] = useState<Tab>(() => (location.hash.replace("#", "") as Tab) || "ops");
  const [selected, setSelected] = useState<string | null>(null);
  const [activity, setActivity] = useState<Activity[]>([]);

  useEffect(() => {
    location.hash = tab;
  }, [tab]);

  const onStream = useCallback((e: StreamEvent) => {
    setVersion((v) => v + 1);
    if (e.kind === "cdm.accepted") {
      const s = e.data as EventSummary;
      const a = s.assessment;
      const pc = a.pc !== null ? `Pc ${sciPlain(a.pc)}` : `refused ${a.refusal_reason}`;
      setActivity((list) =>
        [
          {
            at: e.at,
            text: `CDM ${s.cdm_count} · ${s.primary.name ?? s.primary.id} × ${s.secondary.name ?? s.secondary.id} · ${pc}${
              a.dilution_flag ? " · DILUTED" : ""
            }`,
            tone: (s.band === "RED" ? "bad" : a.dilution_flag || s.band === "AMBER" ? "warn" : "info") as Activity["tone"],
          },
          ...list,
        ].slice(0, 30),
      );
    } else if (e.kind === "cdm.rejected") {
      const d = e.data as { code: string; source: string };
      setActivity((list) => [{ at: e.at, text: `CDM quarantined · ${d.code} (${d.source})`, tone: "bad" as const }, ...list].slice(0, 30));
    }
  }, []);
  const { connected } = useStream(onStream);

  const scope = tab === "library" ? "past" : "active";
  const listPath = tab === "ops" || tab === "library" ? `/api/events?scope=${scope}` : null;
  const { data: events } = useResource<EventSummary[]>(listPath, version);

  const liveEvents = useMemo(
    () =>
      (events ?? []).map((e) => ({
        ...e,
        time_to_mcp_s: (Date.parse(e.mcp) - nowMs) / 1000,
        time_to_tca_s: (Date.parse(e.tca) - nowMs) / 1000,
      })),
    [events, nowMs],
  );

  useEffect(() => {
    if (!events || events.length === 0) return;
    if (!selected || !events.some((e) => e.event_id === selected)) {
      setSelected((events.find((e) => e.needs_attention) ?? events[0]).event_id);
    }
  }, [events, selected]);

  const selectedSummary = liveEvents.find((e) => e.event_id === selected);
  const { data: trajectory } = useResource<Trajectory>(
    selected && (tab === "ops" || tab === "library") ? `/api/events/${encodeURIComponent(selected)}/trajectory` : null,
  );

  const ctx: ExtensionContext = { node, version, nowMs, bump: () => setVersion((v) => v + 1) };
  const extTabs = extensionTabs(node);
  const marking = node?.marking ?? "UNCLASSIFIED";

  return (
    <div className="app">
      <div className="banner banner-top">{marking}</div>
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true">
            <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="3" />
            <circle cx="16" cy="16" r="4" fill="currentColor" />
          </svg>
          <span>Sentinel</span>
        </div>
        <nav className="tabs" role="tablist">
          {[
            ["ops", "Operations"],
            ...extTabs.map((t) => [t.id, t.label]),
            ["library", "NASA reference"],
            ["validation", "Validation"],
          ].map(([id, label]) => (
            <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="status">
          {extTabs.flatMap((t) => (t.status ? [<span key={t.id}>{t.status(ctx)}</span>] : []))}
          <span className={`dot ${connected ? "ok" : "bad"}`} title={connected ? "live stream connected" : "stream disconnected"} />
          <span className="mono">
            {node?.node_id ?? "…"} · {node?.role ?? ""}
          </span>
          <span className="mono clock" title={node?.clock}>
            {zulu(nowMs)}
            {node && node.clock !== "real" ? " SIM" : ""}
          </span>
        </div>
      </header>

      {(tab === "ops" || tab === "library") && (
        <main className="ops">
          <aside className="left">
            <div className="panel-head">
              <h2>{tab === "ops" ? "Active conjunctions" : "NASA CARA reference events"}</h2>
              <span className="muted">
                {tab === "ops" ? "sorted by time to maneuver commit point" : "real, historical - newest first"}
              </span>
            </div>
            <EventList events={liveEvents} selected={selected} onSelect={setSelected} mode={tab === "ops" ? "active" : "past"} />
            {tab === "ops" && (
              <div className="activity">
                <h3>Live feed</h3>
                {activity.length === 0 && <div className="muted">Waiting for CDM updates…</div>}
                {activity.map((a) => (
                  <div key={a.at + a.text} className={`activity-row tone-${a.tone}`}>
                    <span className="mono">{zulu(a.at)}</span> {a.text}
                  </div>
                ))}
              </div>
            )}
          </aside>
          <section className="center">
            <ErrorBoundary label="Globe">
              <Globe
                trajectory={trajectory}
                primaryName={selectedSummary?.primary.name ?? undefined}
                secondaryName={selectedSummary?.secondary.name ?? undefined}
              />
            </ErrorBoundary>
            <div className="globe-note">two-body arcs ±20 min around TCA · visualization only · imagery bundled offline</div>
          </section>
          <aside className="right">
            <ErrorBoundary label="Event detail">
              {selected ? <EventDetail eventId={selected} version={version} /> : <div className="empty">Select an event.</div>}
            </ErrorBoundary>
          </aside>
        </main>
      )}

      {tab === "validation" && (
        <main className="page">
          <ValidationPanel />
        </main>
      )}

      {extTabs.map((t) => (tab === t.id ? <main key={t.id} className="page">{t.render(ctx)}</main> : null))}

      <div className="banner banner-bottom">{marking}</div>
    </div>
  );
}
