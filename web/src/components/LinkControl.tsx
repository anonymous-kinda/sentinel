import { useState } from "react";
import type { LinkInfo } from "../api/types";
import { postJSON, useResource } from "../api/client";
import { useAction } from "../lib/useAction";

const PRESETS = ["CONNECTED", "DEGRADED", "LIMITED", "DENIED"] as const;

/**
 * The measured state of this node's link to its hub, and - on a demo node
 * bound to localhost - presets that shape the real link with Toxiproxy.
 * The state chip is what the sync agent measured, never the preset chosen.
 */
export function LinkControl({ version }: { version: number }) {
  const [local, setLocal] = useState(0);
  const { data } = useResource<LinkInfo>("/api/link", version + local);
  const [open, setOpen] = useState(false);
  const preset = useAction();
  if (!data || data.role !== "edge") return null;
  const state = data.monitor.state;
  const emulation = data.emulation;
  return (
    <span className="link-control">
      <button
        className={`link-chip link-${state.toLowerCase()}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title="Link to hub, as measured by the sync agent"
      >
        LINK {state}
        {data.monitor.rtt_ms !== null && state !== "DENIED" ? ` · ${Math.round(data.monitor.rtt_ms)} ms` : ""}
      </button>
      {open && (
        <div className="link-pop">
          <div className="muted">
            to {data.hub_id} · last success {data.monitor.seconds_since_success ?? "-"} s ago
            {data.monitor.rate_bytes_per_s ? ` · ${Math.round(data.monitor.rate_bytes_per_s)} B/s` : ""}
          </div>
          {emulation !== undefined && emulation !== null ? (
            <>
              <div className="link-pop-head">Emulate (Toxiproxy on the real leaf link)</div>
              <div className="link-presets">
                {PRESETS.map((p) => (
                  <button
                    key={p}
                    className={`btn-small ${emulation.preset === p ? "active" : ""}`}
                    aria-pressed={emulation.preset === p}
                    disabled={preset.busy}
                    onClick={async () => {
                      if (await preset.run(() => postJSON("/api/demo/link", { preset: p }), "Link preset failed", { preset: p })) {
                        setLocal((n) => n + 1);
                      }
                    }}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <div className="muted small">
                {PRESETS.indexOf(emulation.preset as (typeof PRESETS)[number]) >= 0 ? `applied: ${emulation.preset}` : ""}
                {emulation.toxics.length > 0 ? ` · ${emulation.toxics.map((t) => t.type).join(", ")}` : ""}
              </div>
              {preset.error && (
                <div className="form-error" role="alert">
                  {preset.error}
                </div>
              )}
            </>
          ) : (
            <div className="muted small">Link emulation is disabled on this node.</div>
          )}
        </div>
      )}
    </span>
  );
}
