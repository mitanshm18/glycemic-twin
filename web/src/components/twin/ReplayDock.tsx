"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Tip } from "@/components/ui/Tip";
import { createReplay, keys, stepReplay } from "@/lib/api/queries";
import type { TwinState } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { errorCopy } from "@/lib/errors";
import { acceptStep, REPLAY_BEAT_MS, REPLAY_STEPS, replayIndex, replayTotal, replayWindow, type ReplayStepMinutes } from "@/lib/replay";
import { fmtClock, fmtDay, parseNaive } from "@/lib/time";

export const REPLAY_DISCLOSURE =
  "Historical replay of recorded CGMacros data, not live monitoring. At each step the twin is rebuilt from data up to that moment only. The population model was fitted on all participants, including this one, so this is not a held-out evaluation.";

type Phase = "ready" | "playing" | "paused" | "finished" | "error";

interface Props {
  patientId: number;
  state: TwinState;
  dataTo: string | null;
  /** move the page to a replayed moment (the existing URL moment mechanism) */
  onMoment: (asOf: string) => void;
  onExit: () => void;
}

/**
 * Replay controls, docked at the bottom of the Twin page while a replay is open so they stay in
 * reach while the clinician watches the chart, dial and "What changed" follow each step. Driven by
 * the client: one POST /replays/{id}/step at a time, never overlapping; nothing is streamed.
 */
export function ReplayDock({ patientId, state, dataTo, onMoment, onExit }: Props) {
  const qc = useQueryClient();
  const labelId = useId();
  const [span] = useState(() => replayWindow(parseNaive(state.as_of), dataTo ? parseNaive(dataTo) : null));
  const [stepMin, setStepMin] = useState<ReplayStepMinutes>(30);
  const [phase, setPhase] = useState<Phase>("ready");
  const [shownAt, setShownAt] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const replayId = useRef<number | null>(null);
  const session = useRef(0); // bumps on pause / exit: an older play loop stops at its next turn
  const closed = useRef(false); // exited: answers still in flight are dropped
  const movedAway = useRef(false); // the clinician moved the moment themselves: do not pull them back
  const lastShown = useRef<string | null>(null);
  const playing = useRef(false);

  const total = span ? replayTotal(span.start, span.end, stepMin) : 0;
  const index = span && shownAt ? replayIndex(span.start, shownAt, stepMin) : 0;

  /** One step. Resolves true to continue, false to stop. */
  const step = async (): Promise<boolean> => {
    if (!span) return false;
    setBusy(true);
    try {
      if (replayId.current === null) {
        const r = await createReplay({ patientId, startAt: span.start, endAt: span.end, stepMinutes: stepMin });
        replayId.current = r.id;
      }
      const res = await stepReplay(replayId.current);
      // an answer that lands after Pause is still shown (the server cursor has moved past it),
      // unless the replay was closed or the clinician has since chosen another moment
      if (closed.current || movedAway.current) return false;
      if (!acceptStep(res.state.as_of, lastShown.current)) return !res.finished;
      // the page reads this state from the cache: no second request for the same moment
      qc.setQueryData(keys.twin(patientId, res.state.as_of, null), res.state);
      void qc.invalidateQueries({ queryKey: keys.history(patientId) });
      lastShown.current = res.state.as_of;
      setShownAt(res.state.as_of);
      onMoment(res.state.as_of);
      if (res.finished) {
        playing.current = false;
        setPhase("finished");
        return false;
      }
      return true;
    } catch (err) {
      if (closed.current) return false;
      playing.current = false;
      setProblem(errorCopy(err, "the next replay step").title);
      setPhase("error");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const play = async () => {
    const run = ++session.current;
    movedAway.current = false;
    playing.current = true;
    setProblem(null);
    setPhase("playing");
    while (playing.current && run === session.current) {
      const more = await step();
      if (!more || !playing.current || run !== session.current) break;
      await new Promise((r) => setTimeout(r, REPLAY_BEAT_MS));
    }
    if (run === session.current && playing.current) {
      playing.current = false;
      setPhase((p) => (p === "playing" ? "paused" : p));
    }
  };
  const pause = () => {
    session.current++;
    playing.current = false;
    setPhase((p) => (p === "playing" ? "paused" : p));
  };
  const stepOnce = async () => {
    session.current++;
    movedAway.current = false;
    playing.current = false;
    setProblem(null);
    setPhase("paused");
    await step();
  };
  const exit = () => {
    session.current++;
    closed.current = true;
    playing.current = false;
    onExit();
  };

  // the clinician moved the moment themselves (rail, picker, meal marker): the replay pauses there
  useEffect(() => {
    if (!lastShown.current || state.as_of === lastShown.current) return;
    movedAway.current = true;
    if (playing.current) pause();
     
  }, [state.as_of]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && playing.current && pause();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
     
  }, []);
  useEffect(() => {
    closed.current = false; // (re)mounted: StrictMode mounts, unmounts and mounts again in development
    return () => {
      closed.current = true;
      // a counter, not a DOM node: bumping the live value is exactly what stops the play loop
      // eslint-disable-next-line react-hooks/exhaustive-deps
      session.current++;
    };
  }, []);

  const started = replayId.current !== null;
  const shownT = shownAt ? parseNaive(shownAt) : null;

  // rendered into <body>: the page's entrance animation keeps a transform on the workspace, which
  // would otherwise turn `position: fixed` into "fixed to the page" instead of to the viewport
  return createPortal(
    <div className={cx("replay", `replay--${phase}`)} role="region" aria-labelledby={labelId}>
      <div className="replay__id">
        <span id={labelId} className="replay__badge">
          <Icon name="history" size={13} /> Historical replay
        </span>
        <Tip text={REPLAY_DISCLOSURE} focusable label="About historical replay">
          <Icon name="info" size={13} />
        </Tip>
      </div>

      {!span ? (
        <p className="replay__msg">The recording ends at this moment: there is nothing after it to replay.</p>
      ) : (
        <>
          <div className="replay__when">
            <span className="replay__clock mono" aria-live="off">
              {shownT ? `${fmtDay(shownT)} ${fmtClock(shownT)}` : `${fmtDay(parseNaive(span.start))} ${fmtClock(parseNaive(span.start))}`}
            </span>
            <span className="replay__of xsmall muted">
              {started ? `step ${Math.min(index, total)} of ${total}` : `${total} steps to ${fmtDay(parseNaive(span.end))} ${fmtClock(parseNaive(span.end))}`}
            </span>
            <span className="replay__bar" aria-hidden="true">
              <span style={{ transform: `scaleX(${total ? Math.min(1, index / total) : 0})` }} />
            </span>
          </div>

          <div className="replay__controls">
            {/* one button that toggles, so keyboard focus stays on it between Play and Pause */}
            <Button
              size="sm"
              variant={phase === "playing" ? "default" : "primary"}
              onClick={() => (phase === "playing" ? pause() : void play())}
              disabled={phase === "finished" || (busy && phase !== "playing")}
              aria-label={phase === "playing" ? "Pause replay" : started ? "Resume replay" : "Play replay"}
              className="replay__play"
            >
              <Icon name={phase === "playing" ? "pause" : "play"} size={13} /> {phase === "playing" ? "Pause" : started ? "Resume" : "Play"}
            </Button>
            <Button size="sm" onClick={() => void stepOnce()} disabled={phase === "playing" || phase === "finished" || busy} aria-label="Step forward one interval">
              Step <Icon name="chevronRight" size={13} />
            </Button>
            <label className="replay__step">
              <span className="sr-only">Replay step</span>
              <select className="select" value={stepMin} disabled={started} onChange={(e) => setStepMin(Number(e.target.value) as ReplayStepMinutes)}>
                {REPLAY_STEPS.map((m) => (
                  <option key={m} value={m}>
                    every {m} min
                  </option>
                ))}
              </select>
            </label>
            <Button size="sm" variant="ghost" onClick={exit} aria-label="Exit replay">
              <Icon name="x" size={13} /> Exit
            </Button>
          </div>
        </>
      )}

      <p className="replay__status xsmall" role="status">
        {phase === "error"
          ? `Replay paused: ${problem}.`
          : phase === "finished"
            ? "End of the replay window. Exit to keep exploring from here."
            : phase === "paused" && started
              ? "Paused. Explore the twin at this moment, then resume."
              : phase === "playing"
                ? "Replaying recorded data."
                : "Recorded data, not live monitoring."}
        {phase === "error" && (
          <button type="button" className="replay__retry" onClick={() => void stepOnce()}>
            Retry
          </button>
        )}
      </p>
    </div>,
    document.body,
  );
}
