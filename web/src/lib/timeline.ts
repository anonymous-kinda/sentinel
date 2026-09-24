import type { PassSensor, PassWindow } from "../api/types";

/** Geometry for the pass timeline: pure functions of time and width. */

const HOUR_MS = 3_600_000;
const MIN_LABEL_SPACING_PX = 30;

/** Time (ms) to x, clamped to the interval's edges. */
export function timeScale(startMs: number, endMs: number, x0: number, x1: number): (t: number) => number {
  const span = endMs - startMs;
  return (t) => x0 + ((Math.min(Math.max(t, startMs), endMs) - startMs) / span) * (x1 - x0);
}

/** Every whole UTC hour in [startMs, endMs]. */
export function hourTicks(startMs: number, endMs: number): number[] {
  const ticks: number[] = [];
  for (let t = Math.ceil(startMs / HOUR_MS) * HOUR_MS; t <= endMs; t += HOUR_MS) ticks.push(t);
  return ticks;
}

export function zuluHour(ms: number): string {
  return `${String(new Date(ms).getUTCHours()).padStart(2, "0")}Z`;
}

/** Label every n hours, n chosen so labels never crowd. */
export function labelEvery(pxPerHour: number): number {
  return [1, 2, 3, 6, 12].find((n) => n * pxPerHour >= MIN_LABEL_SPACING_PX) ?? 24;
}

export interface ImagerRow {
  norad_id: number;
  name: string;
  sensor: PassSensor;
  windows: PassWindow[];
}

/** One row per imager with windows, in order of its first rise. */
export function imagerRows(windows: PassWindow[]): ImagerRow[] {
  const rows = new Map<number, ImagerRow>();
  for (const w of windows) {
    const row = rows.get(w.norad_id) ?? { norad_id: w.norad_id, name: w.name, sensor: w.sensor, windows: [] };
    row.windows.push(w);
    rows.set(w.norad_id, row);
  }
  return [...rows.values()];
}

export interface GanttLayout {
  width: number;
  height: number;
  plotX0: number;
  plotX1: number;
  bandY: number;
  bandH: number;
  rowH: number;
  rowY: (index: number) => number;
  axisY: number;
}

/** Top to bottom: "now" label, the gap band, one row per imager, the hour axis. */
export function ganttLayout(rowCount: number, width: number): GanttLayout {
  const labelW = Math.round(Math.min(180, Math.max(90, width * 0.2)));
  const bandY = 16;
  const bandH = 26;
  const rowsTop = bandY + bandH + 8;
  const rowH = 24;
  const axisY = rowsTop + rowCount * rowH + 4;
  return {
    width,
    height: axisY + 34,
    plotX0: labelW,
    plotX1: width - 12,
    bandY,
    bandH,
    rowH,
    rowY: (index) => rowsTop + index * rowH,
    axisY,
  };
}
