import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "../api/client";
import { AnswerCard, AssistantPanel, ProbabilityBars, commandFor } from "../components/AssistantPanel";
import type { AiAnswer } from "../api/types";
import { mockApi, ok } from "./fixtures/api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const tier = { router: "jev", narrator: "claude", reason: "Link CONNECTED", link_state: "CONNECTED", marking: "UNCLASSIFIED" } as const;
const base: AiAnswer = {
  status: "answered",
  text: "EX-DEB 118 is RED: Pc 5.0×10⁻³ (Foster-Estes 2D).",
  tier,
  route: {
    tool: "get_assessment",
    args: { event_id: "99001-99118-20260924T070000" },
    confidence: 0.86,
    provider: "jev",
    tool_probabilities: { get_assessment: 0.86, explain_dilution: 0.09, list_events: 0.03, link_status: 0.02 },
    event_probabilities: { "99001-99118-20260924T070000": 0.93, none: 0.07 },
    detail: { model: "jev-1.13.0", latency_ms: 212.4, request_bytes: 1912, response_bytes: 402 },
  },
  facts: { event_id: "99001-99118-20260924T070000" },
  narrated_by: "claude",
  grounding: { ok: true, unsupported: [] },
  withheld: null,
  alternatives: [],
  fallbacks: [],
  draft_id: null,
  audit_seq: 7,
};

describe("ProbabilityBars - Jev's calibrated answer, not just its pick", () => {
  it("sorts the options and shows the top ones as percentages", () => {
    render(<ProbabilityBars probabilities={base.route!.tool_probabilities} top={3} />);
    const labels = screen.getAllByTestId("prob-label").map((n) => n.textContent);
    expect(labels).toEqual(["get assessment", "explain dilution", "list events"]);
    expect(screen.getByText("86%")).toBeTruthy();
  });
});

describe("AnswerCard", () => {
  it("shows who routed it, how sure, and what it cost on the wire", () => {
    render(<AnswerCard answer={base} onAsk={() => {}} onConfirm={async () => ({})} />);
    expect(screen.getByText(/routed by jev/)).toBeTruthy();
    expect(screen.getByText(/1,912 B out/)).toBeTruthy();
    expect(screen.getByText(/numbers grounded/)).toBeTruthy();
  });

  it("says plainly when an AI answer was withheld, and which numbers failed", () => {
    render(
      <AnswerCard
        answer={{ ...base, narrated_by: "template", withheld: { narrator: "claude", unsupported: ["2.0×10⁻²"] } }}
        onAsk={() => {}}
        onConfirm={async () => ({})}
      />,
    );
    expect(screen.getByText(/withheld/)).toBeTruthy();
    expect(screen.getByText(/2\.0×10⁻²/)).toBeTruthy();
  });

  it("offers a draft for confirmation and records it only on confirm", async () => {
    const onConfirm = vi.fn(async () => ({ digest: "abcdef1234567890" }));
    render(
      <AnswerCard
        answer={{ ...base, status: "draft", draft_id: "d1", text: "DRAFT: MANEUVER on ... not recorded until you confirm it." }}
        onAsk={() => {}}
        onConfirm={onConfirm}
      />,
    );
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(onConfirm).toHaveBeenCalledWith("d1", "");
    expect(await screen.findByText(/Recorded as a signed DECISION/)).toBeTruthy();
  });

  it("turns a question back into one-click choices", () => {
    const onAsk = vi.fn();
    const clarify: AiAnswer = {
      ...base,
      status: "clarify",
      text: "Which event?",
      route: { ...base.route!, args: {} },
      alternatives: [{ event_id: "99001-99412-20260924T180000", label: "EXSAT-1 vs EX-DEB 412, AMBER, MCP in 21.0 h", p: 0.4 }],
    };
    render(<AnswerCard answer={clarify} onAsk={onAsk} onConfirm={async () => ({})} />);
    fireEvent.click(screen.getByRole("button", { name: /EX-DEB 412/ }));
    expect(onAsk).toHaveBeenCalledWith("/assess 99412");
  });
});

describe("the server's reason, not a bare status", () => {
  it("shows why the assistant refused a question, and logs it", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi({
      "GET /api/ai/status": ok({ enabled: true, tier, link_source: "measured", cloud_opt_in: true, min_confidence: 0.6 }),
      "GET /api/ai/audit/verify": ok({ ok: true, count: 0 }),
      "POST /api/ai/ask": { status: 503, body: { detail: "the assistant is busy; try again" } },
    });
    render(<AssistantPanel version={0} />);
    fireEvent.change(screen.getByRole("textbox", { name: "question" }), { target: { value: "How is the link?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("the assistant is busy; try again")).toBeTruthy();
    expect(screen.queryByText(/HTTP 503/)).toBeNull();
    expect(consoleError).toHaveBeenCalledWith("Assistant question failed", expect.objectContaining({ status: 503 }));
  });

  it("shows why a draft could not be confirmed", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const onConfirm = vi.fn(async () => {
      throw new HttpError("/api/ai/confirm", 409, { detail: "stale_draft" });
    });
    render(<AnswerCard answer={{ ...base, status: "draft", draft_id: "d1" }} onAsk={() => {}} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(await screen.findByText("stale_draft")).toBeTruthy();
    expect(screen.queryByText(/HTTP 409/)).toBeNull();
  });
});

describe("commandFor", () => {
  it("maps a tool, event and decision to the exact slash command", () => {
    expect(commandFor("draft_decision", "99001-99118-20260924T070000", "MANEUVER")).toBe("/draft 99118 maneuver");
    expect(commandFor("link_status")).toBe("/link");
  });
});
