import { vi } from "vitest";

type Listener = (event: MessageEvent) => void;

/**
 * An EventSource the test drives by hand. jsdom has none, and a real one
 * would need a server. `open`, `drop` and `fail` reproduce what a browser
 * does: a dropped connection is retried by the browser (readyState
 * CONNECTING); an HTTP error such as a proxy's 502 closes it for good.
 */
export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private readonly listeners = new Map<string, Set<Listener>>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  static latest(): FakeEventSource {
    const source = FakeEventSource.instances[FakeEventSource.instances.length - 1];
    if (!source) throw new Error("no EventSource was opened");
    return source;
  }

  static install(): void {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  }

  addEventListener(kind: string, listener: Listener): void {
    if (!this.listeners.has(kind)) this.listeners.set(kind, new Set());
    this.listeners.get(kind)!.add(listener);
  }

  removeEventListener(kind: string, listener: Listener): void {
    this.listeners.get(kind)?.delete(listener);
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }

  // ---------------------------------------------------------- test drivers
  open(): void {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.(new Event("open"));
  }

  /** The connection dropped; the browser will retry it itself. */
  drop(): void {
    this.readyState = FakeEventSource.CONNECTING;
    this.onerror?.(new Event("error"));
  }

  /** An HTTP error: the browser gives up on this source for good. */
  fail(): void {
    this.readyState = FakeEventSource.CLOSED;
    this.onerror?.(new Event("error"));
  }

  emit(kind: string, data: unknown): void {
    if (this.readyState === FakeEventSource.CLOSED) return;
    const event = new MessageEvent(kind, { data: typeof data === "string" ? data : JSON.stringify(data) });
    this.listeners.get(kind)?.forEach((listener) => listener(event));
  }
}
