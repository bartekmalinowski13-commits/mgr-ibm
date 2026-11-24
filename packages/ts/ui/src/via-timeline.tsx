import { cn } from "./cn";

export type ViaState = "done" | "current" | "todo";

export interface ViaStep {
  name: string;
  state: ViaState;
  /** e.g. "18 s", "1 min 02 s", "trwa" (rendered in mono) */
  time?: string;
  /** who executed the step: agent / rules / parser / generator */
  executor?: string;
}

export interface ViaTrack {
  /** accessible name of the track, e.g. "Wariant A: tylko LLM" */
  label: string;
  tone: "llm" | "rule";
  steps: ViaStep[];
}

const TONE = {
  llm: { text: "text-llm", bg: "bg-llm", border: "border-llm" },
  rule: { text: "text-rule", bg: "bg-rule", border: "border-rule" },
} as const;

function Via({ state }: { state: ViaState }) {
  return (
    <svg viewBox="0 0 22 22" width="22" height="22" aria-hidden className="relative z-10 shrink-0">
      {state === "done" ? (
        <>
          <circle cx="11" cy="11" r="9.5" fill="currentColor" />
          <circle cx="11" cy="11" r="3.6" className="fill-sheet" />
        </>
      ) : null}
      {state === "current" ? (
        <>
          <circle
            cx="11"
            cy="11"
            r="9.2"
            className="fill-sheet"
            stroke="currentColor"
            strokeWidth="2.6"
          />
          <circle
            cx="11"
            cy="11"
            r="4.4"
            fill="currentColor"
            className="origin-center motion-safe:animate-[via-pulse_1.6s_ease-in-out_infinite] [transform-box:fill-box]"
          />
        </>
      ) : null}
      {state === "todo" ? (
        <circle
          cx="11"
          cy="11"
          r="9"
          className="fill-sheet"
          stroke="currentColor"
          strokeWidth="1.5"
        />
      ) : null}
    </svg>
  );
}

/**
 * Run steps drawn as copper tracks with vias (ADR-0019): done = filled via with a hole,
 * current = ring with a pulsing centre (the app's only animation), future = empty ring on a
 * dashed segment. One track per variant (A violet above B green).
 */
export function ViaTimeline({
  tracks,
  stateLabels,
  label,
  className,
}: {
  /** accessible name of the (horizontally scrollable) region */
  label?: string;
  tracks: ViaTrack[];
  stateLabels: Record<ViaState, string>;
  className?: string;
}) {
  return (
    <section
      aria-label={label}
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be reachable by keyboard
      tabIndex={0}
      className={cn(
        "relative overflow-x-auto focus-visible:outline-2 focus-visible:outline-ink",
        className,
      )}
    >
      <div className="flex min-w-[620px] flex-col gap-7">
        {tracks.map((track) => {
          const tone = TONE[track.tone];
          return (
            <ol
              key={track.label}
              aria-label={track.label}
              className="grid"
              style={{
                gridTemplateColumns: `repeat(${Math.max(track.steps.length, 1)}, minmax(0, 1fr))`,
              }}
            >
              {track.steps.map((s, i) => {
                const leftSolid = s.state !== "todo";
                const rightSolid = s.state === "done" && track.steps[i + 1]?.state !== "todo";
                return (
                  // biome-ignore lint/suspicious/noArrayIndexKey: steps are an ordered sequence; names can repeat
                  <li key={`${s.name}-${i}`} className="flex flex-col items-center text-center">
                    <span className="mb-2 text-[13.5px] font-semibold leading-tight">{s.name}</span>
                    <span
                      className={cn("relative flex w-full items-center justify-center", tone.text)}
                    >
                      <span
                        aria-hidden
                        className={cn(
                          "absolute left-0 right-1/2 top-1/2 -translate-y-1/2",
                          i === 0 && "left-[30%]",
                          leftSolid
                            ? cn("h-[5px]", tone.bg)
                            : cn("h-0 border-t-[1.5px] border-dashed", tone.border),
                        )}
                      />
                      <span
                        aria-hidden
                        className={cn(
                          "absolute left-1/2 right-0 top-1/2 -translate-y-1/2",
                          i === track.steps.length - 1 && "right-[30%]",
                          rightSolid
                            ? cn("h-[5px]", tone.bg)
                            : cn("h-0 border-t-[1.5px] border-dashed", tone.border),
                        )}
                      />
                      <Via state={s.state} />
                    </span>
                    <span className="mt-1.5 font-data text-[12.5px] text-muted">
                      {s.time ?? "—"}
                    </span>
                    {s.executor ? (
                      <span className={cn("text-[13px]", tone.text)}>{s.executor}</span>
                    ) : null}
                    <span className="sr-only">{stateLabels[s.state]}</span>
                  </li>
                );
              })}
            </ol>
          );
        })}
      </div>
    </section>
  );
}
