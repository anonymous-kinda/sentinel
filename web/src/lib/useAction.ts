import { useState } from "react";
import { HttpError, apiErrorMessage } from "../api/client";
import { log } from "./log";

/**
 * A request the operator asked for: whether it is running, and the server's
 * reason when it failed. A failure is shown, never swallowed, and logged
 * under `failure` (a stable message) with `fields` and the HTTP status.
 */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Resolves true when `action` succeeded. */
  async function run(action: () => Promise<unknown>, failure: string, fields: Record<string, unknown> = {}): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await action();
      return true;
    } catch (e) {
      const reason = apiErrorMessage(e);
      log.error({ ...fields, status: e instanceof HttpError ? e.status : null, error: reason }, failure);
      setError(reason);
      return false;
    } finally {
      setBusy(false);
    }
  }

  return { busy, error, run, clearError: () => setError(null) };
}
