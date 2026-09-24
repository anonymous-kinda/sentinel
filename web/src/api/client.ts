import { useEffect, useRef, useState } from "react";

export async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(`${path}: HTTP ${response.status}`), { payload });
  return payload as T;
}

/** Fetch `path` and refetch whenever `version` changes. Keeps the last good
 *  value while refetching so the console never blanks on an update. */
export function useResource<T>(path: string | null, version = 0): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!path) {
      setData(null);
      return;
    }
    const controller = new AbortController();
    getJSON<T>(path, controller.signal)
      .then((value) => {
        setData(value);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(String(e));
      });
    return () => controller.abort();
  }, [path, version]);
  return { data, error };
}

export interface StreamEvent {
  kind: string;
  data: unknown;
  at: number;
}

/** Server-sent events from this node. The stream is local to the node: it
 *  keeps working when the link to any other node is down. */
export function useStream(onEvent: (e: StreamEvent) => void): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    const source = new EventSource("/api/stream");
    const kinds = [
      "cdm.accepted",
      "cdm.rejected",
      "ops.changed",
      "sync.progress",
      "sync.arrival",
      "link.state",
      "passes.updated",
      "ai.audit",
    ];
    const listeners = kinds.map((kind) => {
      const fn = (ev: MessageEvent) => {
        let data: unknown = null;
        try {
          data = JSON.parse(ev.data);
        } catch {
          data = ev.data;
        }
        handler.current({ kind, data, at: Date.now() });
      };
      source.addEventListener(kind, fn as EventListener);
      return [kind, fn] as const;
    });
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    return () => {
      listeners.forEach(([kind, fn]) => source.removeEventListener(kind, fn as EventListener));
      source.close();
    };
  }, []);
  return { connected };
}
