import { useCallback, useEffect, useMemo, useState } from "react";
import type { Assessment, EventSummary, NodeInfo, Trajectory } from "./api/types";
import { useResource, useStream, type StreamEvent } from "./api/client";
import { EventList } from "./components/EventList";
import { EventDetail } from "./components/EventDetail";
import { Globe } from "./components/Globe";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { LinkControl } from "./components/LinkControl";
import { PcValue } from "./components/PcValue";
import { ValidationPanel } from "./components/ValidationPanel";
import { markingLevel } from "./lib/marking";
import { extensionTabs, type ExtensionContext } from "./extensions";

type Tab = "ops" | "library" | "validation" | string;

/** Until the node reports its marking, the console asserts none. */
export const MARKING_UNKNOWN = "MARKING UNKNOWN";

interface Activity {
  at: number;
  text: string;
  tone: "info" | "warn" | "bad";
  /** A streamed assessment, drawn by PcValue like every other Pc. */
  assessment?: Assessment;
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
  const { data: node, error: nodeError } = useResource<NodeInfo>("/api/node", version);
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
      setActivity((list) =>
        [
          {
            at: e.at,
            text: `CDM ${s.cdm_count} · ${s.primary.name ?? s.primary.id} × ${s.secondary.name ?? s.secondary.id}`,
            tone: (s.band === "RED" ? "bad" : a.dilution_flag || s.band === "AMBER" ? "warn" : "info") as Activity["tone"],
            assessment: a,
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
  const tabs = [["ops", "Operations"], ...extTabs.map((t) => [t.id, t.label]), ["library", "NASA reference"], ["validation", "Validation"]];
  const known = tabs.some(([id]) => id === tab);

  // A bookmarked tab for a module this node does not run opens Operations,
  // once the node has said what it runs (or cannot say).
  useEffect(() => {
    if (!known && (node || nodeError)) setTab("ops");
  }, [known, node, nodeError]);

  const marking = node?.marking ?? MARKING_UNKNOWN;
  const bannerClass = `banner-${markingLevel(node?.marking ?? null)}`;

  return (
    <div className="app">
      <div className={`banner banner-top ${bannerClass}`}>{marking}</div>
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true">
            <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="3" />
            <circle cx="16" cy="16" r="4" fill="currentColor" />
          </svg>
          <span>Sentinel</span>
        </div>
        <nav className="tabs" role="tablist">
          {tabs.map(([id, label]) => (
            <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="status">
          {extTabs.flatMap((t) => (t.status ? [<span key={t.id}>{t.status(ctx)}</span>] : []))}
          <LinkControl version={version} />
          <StreamStatus connected={connected} />
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
            <ErrorBoundary label="Event list" resetKey={events}>
              <EventList events={liveEvents} selected={selected} onSelect={setSelected} mode={tab === "ops" ? "active" : "past"} />
            </ErrorBoundary>
            {tab === "ops" && (
              <div className="activity">
                <h3>Live feed</h3>
                {activity.length === 0 && <div className="muted">Waiting for CDM updates…</div>}
                <ErrorBoundary label="Live feed" resetKey={activity}>
                  {activity.map((a) => (
                    <div key={a.at + a.text} className={`activity-row tone-${a.tone}`}>
                      <span className="mono">{zulu(a.at)}</span> {a.text}
                      {a.assessment && <FeedPc assessment={a.assessment} />}
                    </div>
                  ))}
                </ErrorBoundary>
              </div>
            )}
          </aside>
          <section className="center">
            <ErrorBoundary label="Globe" resetKey={selected}>
              <Globe
                trajectory={trajectory}
                primaryName={selectedSummary?.primary.name ?? undefined}
                secondaryName={selectedSummary?.secondary.name ?? undefined}
              />
            </ErrorBoundary>
            <div className="globe-note">two-body arcs ±20 min around TCA · visualization only · imagery bundled offline</div>
          </section>
          <aside className="right">
            <ErrorBoundary label="Event detail" resetKey={selected}>
              {selected ? (
                <EventDetail eventId={selected} version={version} readOnly={node?.read_only ?? true} hasOps={node?.modules.includes("ops") ?? false} />
              ) : (
                <div className="empty">Select an event.</div>
              )}
            </ErrorBoundary>
          </aside>
        </main>
      )}

      {tab === "validation" && (
        <main className="page">
          <ErrorBoundary label="Validation">
            <ValidationPanel />
          </ErrorBoundary>
        </main>
      )}

      {extTabs.map((t) =>
        tab === t.id ? (
          <main key={t.id} className="page">
            <ErrorBoundary label={t.label}>{t.render(ctx)}</ErrorBoundary>
          </main>
        ) : null,
      )}

      <div className={`banner banner-bottom ${bannerClass}`}>{marking}</div>
    </div>
  );
}

/** Whether the live stream is up, in words as well as colour. */
function StreamStatus({ connected }: { connected: boolean }) {
  return (
    <span className="stream-status" role="status" aria-label="Live stream">
      <span className={`dot ${connected ? "ok" : "bad"}`} aria-hidden="true" />
      {connected ? "live" : "no stream"}
    </span>
  );
}

/** A streamed Pc in the live feed: through PcValue, with the refusal
 *  reason or the dilution spelled out beside it. */
function FeedPc({ assessment: a }: { assessment: Assessment }) {
  return (
    <>
      {" · "}
      <PcValue assessment={a} size="sm" />
      {a.method === "REFUSED" && ` · ${a.refusal_reason}`}
      {a.dilution_flag && " · DILUTED"}
    </>
  );
}
