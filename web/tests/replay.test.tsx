import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { REPLAY_DISCLOSURE, ReplayDock } from "@/components/twin/ReplayDock";
import type { TwinState } from "@/lib/api/types";
import { acceptStep, replayIndex, replayTotal, replayWindow } from "@/lib/replay";
import { HOUR, MINUTE, parseNaive } from "@/lib/time";
import fixture from "./fixtures/twin-state.synthetic.json";

// SYNTHETIC fixture: produced by the real twin_core engine on the synthetic test record.
const STATE = fixture as unknown as TwinState;
const T0 = parseNaive(STATE.as_of);

describe("replay window and steps", () => {
  it("replays up to 24 h from the moment, never past the recording", () => {
    expect(replayWindow(T0, null)).toEqual({ start: "2021-06-06T19:00:00", end: "2021-06-07T19:00:00" });
    expect(replayWindow(T0, T0 + 5 * HOUR)).toEqual({ start: "2021-06-06T19:00:00", end: "2021-06-07T00:00:00" });
    expect(replayWindow(T0, T0 + 10 * MINUTE)).toBeNull(); // nothing left to replay
  });
  it("counts the start, every step and the (possibly shorter) last one", () => {
    expect(replayTotal("2021-06-06T19:00:00", "2021-06-07T19:00:00", 30)).toBe(49);
    expect(replayTotal("2021-06-06T19:00:00", "2021-06-06T20:10:00", 30)).toBe(4); // 19:00 19:30 20:00 20:10
    expect(replayIndex("2021-06-06T19:00:00", "2021-06-06T20:00:00", 30)).toBe(3);
  });
  it("only shows answers that move forward in time", () => {
    expect(acceptStep("2021-06-06T19:30:00", null)).toBe(true);
    expect(acceptStep("2021-06-06T19:30:00", "2021-06-06T19:00:00")).toBe(true);
    expect(acceptStep("2021-06-06T19:00:00", "2021-06-06T19:00:00")).toBe(false); // a repeat
    expect(acceptStep("2021-06-06T18:30:00", "2021-06-06T19:00:00")).toBe(false); // out of order
  });
});

/** The replay API as the server answers it: a cursor that only moves forward, capped at the end. */
function replayServer(opts: { failOnStep?: number } = {}) {
  const calls: Array<{ url: string; body: unknown }> = [];
  let cursor = T0;
  let end = T0;
  let steps = 0;
  const iso = (t: number) => new Date(t).toISOString().slice(0, 19);
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, body });
    const ok = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
    if (url.includes("/auth/csrf")) return ok({ csrf_token: "t" });
    if (url.endsWith("/replays")) {
      end = parseNaive(body.end_at);
      return ok({ id: 7, patient_id: 7, start_at: body.start_at, end_at: body.end_at, cursor_at: body.start_at, step_minutes: body.step_minutes, last_state_id: null }, 201);
    }
    if (url.endsWith("/replays/7/step")) {
      steps++;
      if (opts.failOnStep === steps) return ok({ error: { code: "INTERNAL_ERROR", message: "unexpected server error" } }, 500);
      const at = cursor;
      const finished = at >= end;
      cursor = Math.min(at + 30 * MINUTE, end);
      return ok({ replay: { id: 7, cursor_at: iso(cursor) }, state: { ...STATE, as_of: iso(at), state_id: `s-${at}` }, finished });
    }
    return ok({ error: { code: "NOT_FOUND", message: "x" } }, 404);
  }) as typeof fetch;
  return calls;
}

function renderDock(onMoment = vi.fn(), onExit = vi.fn(), dataTo: string | null = "2021-06-06T20:00:00") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ReplayDock patientId={7} state={STATE} dataTo={dataTo} onMoment={onMoment} onExit={onExit} />
    </QueryClientProvider>,
  );
  return { onMoment, onExit, qc };
}

describe("replay dock", () => {
  it("says plainly what it is: historical, not live, not held out", () => {
    replayServer();
    renderDock();
    expect(screen.getByRole("region", { name: "Historical replay" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About historical replay" })).toHaveAccessibleDescription(REPLAY_DISCLOSURE);
    expect(REPLAY_DISCLOSURE).toMatch(/not live monitoring/);
    expect(REPLAY_DISCLOSURE).toMatch(/not a held-out evaluation/);
    expect(REPLAY_DISCLOSURE).toMatch(/data up to that moment only/);
    expect(screen.getByText("Recorded data, not live monitoring.")).toBeInTheDocument();
  });

  it("creates one replay from the twin's moment and steps it forward, feeding the page's cache", async () => {
    const calls = replayServer();
    const { onMoment, qc } = renderDock();
    fireEvent.click(screen.getByRole("button", { name: "Step forward one interval" }));
    await waitFor(() => expect(onMoment).toHaveBeenCalledWith("2021-06-06T19:00:00"));
    expect(calls.find((c) => c.url.endsWith("/replays"))?.body).toEqual({ patient_id: 7, start_at: "2021-06-06T19:00:00", end_at: "2021-06-06T20:00:00", step_minutes: 30 });
    expect(qc.getQueryData(["patient", 7, "twin", "2021-06-06T19:00:00", null])).toMatchObject({ state_id: `s-${T0}` });
    await waitFor(() => expect(screen.getByRole("button", { name: "Step forward one interval" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Step forward one interval" }));
    await waitFor(() => expect(onMoment).toHaveBeenLastCalledWith("2021-06-06T19:30:00"));
    expect(calls.filter((c) => c.url.endsWith("/replays"))).toHaveLength(1); // one session, many steps
    expect(screen.getByText("step 2 of 3")).toBeInTheDocument();
  });

  it("plays to the end of the window and stops there", async () => {
    replayServer();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { onMoment } = renderDock();
    fireEvent.click(screen.getByRole("button", { name: "Play replay" }));
    await waitFor(() => expect(screen.getByText(/End of the replay window/)).toBeInTheDocument(), { timeout: 10_000 });
    expect(onMoment.mock.calls.map((c) => c[0])).toEqual(["2021-06-06T19:00:00", "2021-06-06T19:30:00", "2021-06-06T20:00:00"]);
    expect(screen.getByRole("button", { name: "Resume replay" })).toBeDisabled();
    vi.useRealTimers();
  });

  it("pauses on a failed step, says so calmly, and retries", async () => {
    replayServer({ failOnStep: 1 });
    const { onMoment } = renderDock();
    fireEvent.click(screen.getByRole("button", { name: "Step forward one interval" }));
    expect(await screen.findByText(/Replay paused:/)).toBeInTheDocument();
    expect(onMoment).not.toHaveBeenCalled(); // nothing fabricated in place of the missing step
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(onMoment).toHaveBeenCalledTimes(1));
  });

  it("exits without applying an answer that is still in flight", async () => {
    replayServer();
    const { onMoment, onExit } = renderDock();
    fireEvent.click(screen.getByRole("button", { name: "Step forward one interval" }));
    fireEvent.click(screen.getByRole("button", { name: "Exit replay" }));
    expect(onExit).toHaveBeenCalled();
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(onMoment).not.toHaveBeenCalled();
  });
});
