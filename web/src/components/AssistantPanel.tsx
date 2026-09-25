import { useState } from "react";
import type { AiAnswer, AiRoute, AiStatus } from "../api/types";
import { HttpError, apiErrorMessage, postJSON, useResource } from "../api/client";
import { log } from "../lib/log";
import { useAction } from "../lib/useAction";

/**
 * The assistant: System One routes (Jev, or local rules), code computes,
 * System Two phrases (Claude, or templates). This panel shows the operator
 * which tier is running and why, how sure the router was - the whole
 * probability distribution, not just its pick - what each decision cost on
 * the wire, and whether every number in the answer traces to a tool result.
 * Drafts are recorded only when a person confirms them.
 */

const COMMANDS: Record<string, string> = {
  list_events: "/events",
  get_assessment: "/assess",
  explain_dilution: "/explain",
  link_status: "/link",
  sync_queue: "/queue",
  draft_decision: "/draft",
};
const STATUS: Record<AiAnswer["status"], string> = { answered: "ANSWER", clarify: "ASKING BACK", draft: "DRAFT" };
const EXAMPLES = [
  "/events red",
  "What needs a decision in the next 12 hours?",
  "Is the 412 probability diluted?",
  "How is the link?",
  "Draft a maneuver decision for 118",
];

const label = (name: string) => name.replace(/_/g, " ");
const catalogNumber = (eventId: string) => eventId.split("-")[1] ?? eventId;
const eventLabel = (eventId: string) => (eventId === "none" ? "no specific event" : `object ${catalogNumber(eventId)}`);
const bytes = (n: number | undefined) => (n === undefined ? "-" : n.toLocaleString("en-US"));

/** The exact slash command for a tool call: what a one-click choice sends. */
export function commandFor(tool: string, eventId?: string, decision?: string): string {
  return [COMMANDS[tool] ?? "/events", eventId && catalogNumber(eventId), decision?.toLowerCase()].filter(Boolean).join(" ");
}

function alternativeCommand(alt: AiAnswer["alternatives"][number], route: AiRoute | null): string {
  const decision = route?.args.decision as string | undefined;
  if (alt.event_id) return commandFor(route?.tool ?? "get_assessment", alt.event_id, decision);
  return commandFor(alt.tool ?? "list_events", route?.args.event_id as string | undefined, alt.tool === "draft_decision" ? decision : undefined);
}

export function ProbabilityBars({
  probabilities,
  top = 4,
  labelOf = label,
}: {
  probabilities: Record<string, number>;
  top?: number;
  labelOf?: (key: string) => string;
}) {
  const rows = Object.entries(probabilities)
    .sort((a, b) => b[1] - a[1])
    .slice(0, top);
  return (
    <div className="prob-bars">
      {rows.map(([key, p]) => (
        <div className="prob-row" key={key}>
          <span className="prob-label" data-testid="prob-label">
            {labelOf(key)}
          </span>
          <span className="prob-track">
            <span className="prob-fill" style={{ width: `${Math.max(1, p * 100)}%` }} />
          </span>
          <span className="prob-p mono">{Math.round(p * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

export function AnswerCard({
  answer,
  onAsk,
  onConfirm,
}: {
  answer: AiAnswer;
  onAsk: (text: string) => void;
  onConfirm: (draftId: string, rationale: string) => Promise<{ digest?: string }>;
}) {
  const [rationale, setRationale] = useState("");
  const [recorded, setRecorded] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const route = answer.route;
  const detail = route?.detail ?? {};

  async function confirm() {
    const draftId = answer.draft_id as string;
    await run(
      async () => setRecorded((await onConfirm(draftId, rationale)).digest ?? ""),
      "Assistant draft confirm failed",
      { draft_id: draftId },
    );
  }

  return (
    <article className={`answer answer-${answer.status}`}>
      <header className="answer-head">
        <span className={`chip status-${answer.status}`}>{STATUS[answer.status]}</span>
        {route && (
          <span className="chip">
            routed by {route.provider} · {route.confidence.toFixed(2)}
          </span>
        )}
        {answer.narrated_by && <span className="chip">written by {answer.narrated_by}</span>}
        {answer.grounding &&
          (answer.grounding.ok ? (
            <span className="chip chip-good" title="Every number in this answer appears in the tool results">
              numbers grounded ✓
            </span>
          ) : (
            <span className="chip chip-bad">numbers not grounded</span>
          ))}
      </header>

      {answer.fallbacks.map((f) => (
        <div className="answer-note warn" key={f.from}>
          {f.from} unavailable ({f.reason}) - answered with {f.to}.
        </div>
      ))}
      {answer.withheld && (
        <div className="answer-note bad">
          The {answer.withheld.narrator} answer was withheld: it stated {answer.withheld.unsupported.join(", ")}, which the
          tool results do not contain. Showing the facts instead.
        </div>
      )}

      <pre className="answer-text">{answer.text}</pre>

      {answer.alternatives.length > 0 && (
        <div className="answer-alts">
          {answer.alternatives.map((alt) => (
            <button key={alt.event_id ?? alt.tool} className="btn-small" onClick={() => onAsk(alternativeCommand(alt, route))}>
              {alt.label ?? alt.description ?? label(alt.tool ?? "")}
              {alt.p !== null && alt.p !== undefined ? ` · ${Math.round(alt.p * 100)}%` : ""}
            </button>
          ))}
        </div>
      )}

      {answer.status === "draft" &&
        answer.draft_id &&
        (recorded !== null ? (
          <div className="answer-note good">Recorded as a signed DECISION{recorded ? ` · ${recorded.slice(0, 12)}` : ""}</div>
        ) : (
          <div className="confirm-form">
            <input
              placeholder="rationale (optional)"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              aria-label="rationale"
            />
            <button className="btn-primary" onClick={confirm} disabled={busy}>
              Confirm and sign
            </button>
            {error && <span className="form-error">{error}</span>}
          </div>
        ))}

      {route && route.provider === "jev" && (
        <details className="answer-why" open>
          <summary>Why this route</summary>
          <div className="why-grid">
            <div>
              <h5>tool</h5>
              <ProbabilityBars probabilities={route.tool_probabilities} />
            </div>
            {Object.keys(route.event_probabilities).length > 0 && (
              <div>
                <h5>event</h5>
                <ProbabilityBars probabilities={route.event_probabilities} top={3} labelOf={eventLabel} />
              </div>
            )}
          </div>
          <div className="muted small mono">
            {detail.model} · {bytes(detail.request_bytes)} B out / {bytes(detail.response_bytes)} B back
            {detail.latency_ms !== undefined ? ` · ${Math.round(detail.latency_ms)} ms` : ""}
          </div>
        </details>
      )}
    </article>
  );
}

export function AiTierBadge({ version }: { version: number }) {
  const { data } = useResource<AiStatus>("/api/ai/status", version);
  if (!data?.enabled || !data.tier) return null;
  const hosted = data.tier.router === "jev" || data.tier.narrator === "claude";
  return (
    <span className={`chip ai-badge ${hosted ? "ai-hosted" : "ai-local"}`} title={data.tier.reason}>
      AI {hosted ? [data.tier.router === "jev" && "JEV", data.tier.narrator === "claude" && "CLAUDE"].filter(Boolean).join("+") : "LOCAL"}
    </span>
  );
}

interface Turn {
  question: string;
  answer?: AiAnswer;
  error?: string;
}

export function AssistantPanel({ version }: { version: number }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: status } = useResource<AiStatus>("/api/ai/status", version);
  const { data: chain } = useResource<{ ok: boolean; count: number }>("/api/ai/audit/verify", version + turns.length);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setText("");
    try {
      const answer = await postJSON<AiAnswer>("/api/ai/ask", { text: q });
      setTurns((t) => [{ question: q, answer }, ...t]);
    } catch (e) {
      const reason = apiErrorMessage(e);
      log.error({ status: e instanceof HttpError ? e.status : null, error: reason }, "Assistant question failed");
      setTurns((t) => [{ question: q, error: reason }, ...t]);
    } finally {
      setBusy(false);
    }
  }

  const confirm = (draftId: string, rationale: string) =>
    postJSON<{ digest?: string }>("/api/ai/confirm", { draft_id: draftId, rationale });

  if (status && !status.enabled) return <div className="empty">The assistant is switched off on this node.</div>;
  const tier = status?.tier;

  return (
    <div className="assistant">
      <aside className="assistant-side">
        <p className="lede">
          <b>Code computes every number.</b> AI chooses which tool answers a request and phrases the result; an answer that
          states a number the tool results do not contain is withheld. Anything that would be recorded is a draft until you
          confirm it.
        </p>
        {tier && (
          <div className="cards tier-cards">
            <div className="card">
              <span className="card-k">System One · routing</span>
              <span className="card-v tier-v">{tier.router === "jev" ? "Jev" : "Local rules"}</span>
              <span className="muted small">{tier.router === "jev" ? status?.models?.jev : "keywords and slash commands"}</span>
            </div>
            <div className="card">
              <span className="card-k">System Two · wording</span>
              <span className="card-v tier-v">{tier.narrator === "claude" ? "Claude" : "Templates"}</span>
              <span className="muted small">{tier.narrator === "claude" ? status?.models?.claude : "deterministic, always grounded"}</span>
            </div>
          </div>
        )}
        {tier && (
          <dl className="tier-facts">
            <div>
              <dt>why this tier</dt>
              <dd>{tier.reason}</dd>
            </div>
            <div>
              <dt>link</dt>
              <dd>
                <span className={`link-text-${tier.link_state.toLowerCase()}`}>{tier.link_state}</span> ({status?.link_source})
              </dd>
            </div>
            <div>
              <dt>marking</dt>
              <dd>{tier.marking}</dd>
            </div>
            <div>
              <dt>hosted AI</dt>
              <dd>
                {status?.cloud_opt_in ? "approved on this node" : "not approved on this node"} · Jev{" "}
                {status?.providers?.jev ? "configured" : "not configured"} · Claude{" "}
                {status?.providers?.claude ? "configured" : "not configured"}
              </dd>
            </div>
            <div>
              <dt>ask back below</dt>
              <dd>confidence {status?.min_confidence}</dd>
            </div>
            <div>
              <dt>audit chain</dt>
              <dd className={chain?.ok === false ? "bad" : "good"}>
                {chain ? `${chain.count} entries · ${chain.ok ? "verified ✓" : "BROKEN"}` : "…"}
              </dd>
            </div>
          </dl>
        )}
        <h4 className="side-head">Try</h4>
        <div className="answer-alts">
          {EXAMPLES.map((e) => (
            <button key={e} className="btn-small" onClick={() => ask(e)} disabled={busy}>
              {e}
            </button>
          ))}
        </div>
      </aside>

      <section className="assistant-main">
        <form
          className="ask-form"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(text);
          }}
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Ask about events, dilution, the link or the sync queue - or /events, /assess 118, /draft 118 monitor"
            aria-label="question"
            maxLength={2000}
          />
          <button className="btn-primary" disabled={busy || !text.trim()}>
            {busy ? "…" : "Ask"}
          </button>
        </form>
        {turns.length === 0 && <div className="empty">Ask a question, or pick one on the left.</div>}
        {turns.map((t, i) => (
          <div className="turn" key={turns.length - i}>
            <div className="turn-q">
              <span className="muted">operator ›</span> {t.question}
            </div>
            {t.answer ? (
              <AnswerCard answer={t.answer} onAsk={ask} onConfirm={confirm} />
            ) : (
              <div className="answer-note bad">{t.error}</div>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
