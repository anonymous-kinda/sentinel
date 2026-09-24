import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "../api/client";
import { UnitForm } from "../components/passes/UnitForm";
import { unit } from "./fixtures/passes";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const PRIVACY = "Stays on this node. The unit's position is never sent to the hub.";

function renderForm(props: Partial<Parameters<typeof UnitForm>[0]> = {}) {
  const onSave = vi.fn(async () => {});
  const onDelete = vi.fn(async () => {});
  render(<UnitForm unit={unit} readOnly={false} onSave={onSave} onDelete={onDelete} {...props} />);
  return { onSave, onDelete };
}

function fill(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("UnitForm - the unit's position, kept on this node", () => {
  it("shows the unit: id, position to 4 decimals, altitude and reaction time", () => {
    renderForm();
    expect(screen.getByText("EX-UNIT-1")).toBeTruthy();
    expect(screen.getByText("35.2600, -116.6800")).toBeTruthy();
    expect(screen.getByText("700 m")).toBeTruthy();
    expect(screen.getByText("30 min")).toBeTruthy();
    expect(screen.getByText(PRIVACY)).toBeTruthy();
  });

  it("has an empty state that asks for a unit, and still states where the position stays", () => {
    renderForm({ unit: null });
    expect(screen.getByText(/No unit set/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Set unit" })).toBeTruthy();
    expect(screen.getByText(PRIVACY)).toBeTruthy();
  });

  it("checks the ICD's rules before sending, and sends nothing when they fail", () => {
    const { onSave } = renderForm();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fill(/latitude/i, "95");
    fill(/reaction time/i, "0");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Latitude must be within -90 to 90 degrees.")).toBeTruthy();
    expect(screen.getByText("Reaction time must be a positive number of minutes.")).toBeTruthy();
    expect(screen.getByLabelText(/latitude/i).getAttribute("aria-invalid")).toBe("true");
    expect(onSave).not.toHaveBeenCalled();
  });

  it("saves a valid edit as numbers, then shows the unit again", async () => {
    const { onSave } = renderForm();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fill(/longitude/i, "-116.7");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith({ ...unit, lon_deg: -116.7 });
    expect(await screen.findByRole("button", { name: "Edit" })).toBeTruthy();
  });

  it("starts a new unit from the model's defaults", () => {
    renderForm({ unit: null });
    fireEvent.click(screen.getByRole("button", { name: "Set unit" }));
    expect((screen.getByLabelText(/altitude/i) as HTMLInputElement).value).toBe("0");
    expect((screen.getByLabelText(/reaction time/i) as HTMLInputElement).value).toBe("30");
  });

  it("shows the server's reason when it refuses, keeps the edit, and logs it", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const refusal = new HttpError("/api/passes/unit", 422, { detail: "latitude outside [-90, 90]" });
    renderForm({ onSave: vi.fn(async () => Promise.reject(refusal)) });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toContain("latitude outside [-90, 90]");
    expect(screen.getByRole("button", { name: "Save" })).toBeTruthy();
    expect(logged).toHaveBeenCalledWith("Pass unit save failed", expect.objectContaining({ status: 422 }));
  });

  it("deletes the unit, and shows why when the server refuses", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const onDelete = vi.fn(async () => Promise.reject(new HttpError("/api/passes/unit", 403, { detail: "this node is read-only" })));
    renderForm({ onDelete });
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalled();
    expect((await screen.findByRole("alert")).textContent).toContain("this node is read-only");
  });

  it("is disabled on a read-only node, and says so", () => {
    renderForm({ readOnly: true });
    expect((screen.getByRole("button", { name: "Edit" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Delete" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/read-only/)).toBeTruthy();
  });
});
