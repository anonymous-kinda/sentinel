import { useEffect, useRef, useState } from "react";
import { log } from "../lib/log";

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
  const { reason, field, code } = (detail ?? {}) as { reason?: unknown; field?: unknown; code?: unknown };
  if (typeof reason === "string" && reason) {
    const about = field ?? code;
    return typeof about === "string" && about ? `${about}: ${reason}` : reason;
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

interface Resource<T> {
  data: T | null;
  error: string | null;
  status: number | null;
}

const NOTHING: Resource<never> = { data: null, error: null, status: null };

/** Fetch `path` and refetch whenever `version` changes. Keeps the last good
 *  value of the same path while refetching, so the console never blanks on
 *  an update; a new path starts empty, so one event's data never shows
 *  under another's name. `error` is the server's reason for the last
 *  failure and `status` its HTTP status; both are null after a success. */
export function useResource<T>(path: string | null, version = 0): Resource<T> {
  const [held, setHeld] = useState<Resource<T> & { path: string | null }>({ ...NOTHING, path: null });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    getJSON<T>(path, controller.signal)
      .then((data) => setHeld({ path, data, error: null, status: null }))
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        const failure = { error: apiErrorMessage(e), status: e instanceof HttpError ? e.status : null };
        setHeld((last) => ({ path, data: last.path === path ? last.data : null, ...failure }));
      });
    return () => controller.abort();
  }, [path, version]);
  if (!path || held.path !== path) return NOTHING;
  return { data: held.data, error: held.error, status: held.status };
}

export interface StreamEvent {
  kind: string;
  data: unknown;
  at: number;
}

/** Not a node event: the stream (re)opened. Events published while it was
 *  down are lost, so a listener refetches what it shows. */
export const STREAM_OPENED = "stream.opened";

/** The server's own `retry:` interval. */
const RECONNECT_MS = 3000;

/** Server-sent events from this node. The stream is local to the node: it
 *  keeps working when the link to any other node is down. The browser
 *  retries a dropped connection by itself but gives up for good on an HTTP
 *  error, such as a proxy's 502 while the node restarts; then this hook
 *  opens a new stream after the retry interval. */
export function useStream(onEvent: (e: StreamEvent) => void): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
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
    const emit = (kind: string, data: unknown) => handler.current({ kind, data, at: Date.now() });
    let source: EventSource;
    let reconnect: number | undefined;
    const connect = () => {
      source = new EventSource("/api/stream");
      for (const kind of kinds) {
        source.addEventListener(kind, ((ev: MessageEvent) => emit(kind, parseEventData(ev.data))) as EventListener);
      }
      source.onopen = () => {
        setConnected(true);
        emit(STREAM_OPENED, null);
      };
      source.onerror = () => {
        setConnected(false);
        if (source.readyState !== EventSource.CLOSED) return; // the browser is retrying
        log.warn({ retry_ms: RECONNECT_MS }, "Event stream closed, reconnecting");
        reconnect = window.setTimeout(connect, RECONNECT_MS);
      };
    };
    connect();
    return () => {
      window.clearTimeout(reconnect);
      source.close();
    };
  }, []);
  return { connected };
}

function parseEventData(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return data;
  }
}
