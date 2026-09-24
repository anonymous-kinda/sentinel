import { useEffect, useRef, useState } from "react";

/** A non-2xx reply: the status code and whatever body the server sent. */
export class HttpError extends Error {
  constructor(
    readonly path: string,
    readonly status: number,
    readonly payload: unknown,
  ) {
    super(`${path}: HTTP ${status}`);
  }
}

/** The server's own reason for an error - FastAPI's `detail`, as a string or
 *  a validation list - or the error itself when there is none. */
export function apiErrorMessage(error: unknown): string {
  if (!(error instanceof HttpError)) return String(error);
  const detail = (error.payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((d) => (d as { msg?: unknown })?.msg ?? JSON.stringify(d)).join("; ");
  }
  return error.message;
}

export async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new HttpError(path, response.status, await response.json().catch(() => null));
  return (await response.json()) as T;
}

async function sendJSON<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new HttpError(path, response.status, payload);
  return payload as T;
}

export const postJSON = <T,>(path: string, body: unknown) => sendJSON<T>("POST", path, body);
export const putJSON = <T,>(path: string, body: unknown) => sendJSON<T>("PUT", path, body);
export const deleteJSON = <T = unknown,>(path: string) => sendJSON<T>("DELETE", path);

/** Fetch `path` and refetch whenever `version` changes. Keeps the last good
 *  value while refetching so the console never blanks on an update. `error`
 *  is the server's reason for the last failure and `status` its HTTP status;
 *  both are null after a success. */
export function useResource<T>(
  path: string | null,
  version = 0,
): { data: T | null; error: string | null; status: number | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<number | null>(null);
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
        setStatus(null);
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setError(apiErrorMessage(e));
        setStatus(e instanceof HttpError ? e.status : null);
      });
    return () => controller.abort();
  }, [path, version]);
  return { data, error, status };
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
      "link.emulation",
      "passes.updated",
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
