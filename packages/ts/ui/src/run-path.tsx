import { type CSSProperties, useLayoutEffect, useRef, useState } from "react";
import { cn } from "./cn";

export type PathActor = "llm" | "rule" | "parser" | "user";
export type PathStepState = "done" | "running" | "pending";

export interface PathStep {
  id: string;
  /** visible label under the node */
  label: string;
  /** who executed the stage: sets the colour of its segment and node */
  actor: PathActor;
  /** second line under the label, e.g. "LLM" / "rules" / "2.4 s" */
  detail?: string;
  state?: PathStepState;
}

export interface RunPathProps {
  steps: PathStep[];
  /** A = LLM-only, B = hybrid: colours the frame label; the segments follow `actor` */
  variant: "A" | "B";
  /** full textual description for assistive technology (role="img") */
  description: string;
  /** index of the stage that has just finished: its segment is drawn in 240ms */
  drawIndex?: number;
  /** the last node is filled: the run is complete */
  complete?: boolean;
  className?: string;
}

const COLOR: Record<PathActor, string> = {
  llm: "var(--color-prov-llm)",
  rule: "var(--color-prov-rule)",
  parser: "var(--color-parser)",
  user: "var(--color-ink)",
};
/** Cell width per stage (adapts to the container between MIN_W and MAX_W), node size and the two path levels (45 degrees: bend dx = dy). */
const MIN_W = 80;
const MAX_W = 140;
const NODE = 16;
const HIGH = 18;
const LOW = 42;
const BEND = LOW - HIGH;
const HEIGHT = 60;

function nodeX(i: number, w: number): number {
  return w / 2 + i * w;
}
function nodeY(i: number): number {
  return i % 2 === 0 ? LOW : HIGH;
}

/**
 * Run path: stages joined by 3px segments bent at 45 degrees, square via-style nodes (16px,
 * 3px outline), the last node filled when the run is done. A segment's colour says who
 * performed the stage. One SVG, no external state; the finished stage draws in 240ms
 * (`prefers-reduced-motion`: instantly, see styles.css).
 */
export function RunPath({
  steps,
  variant,
  description,
  drawIndex,
  complete,
  className,
}: RunPathProps) {
  const n = steps.length;
  const box = useRef<HTMLDivElement>(null);
  const [avail, setAvail] = useState(0);
  const [scrolls, setScrolls] = useState(false);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setAvail(el.clientWidth);
    setScrolls(el.scrollWidth > el.clientWidth + 1);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      setAvail(el.clientWidth);
      setScrolls(el.scrollWidth > el.clientWidth + 1);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // cell width: fill the container, between MIN_W and MAX_W (scrolls below the minimum)
  const W = Math.min(MAX_W, Math.max(MIN_W, Math.floor(avail / (n + 1)) || MAX_W));
  const width = (n + 1) * W;
  const segment = (i: number): { d: string; len: number } => {
    const x0 = nodeX(i, W);
    const x1 = nodeX(i + 1, W);
    const y0 = nodeY(i);
    const y1 = nodeY(i + 1);
    const run = x1 - BEND - x0;
    return { d: `M${x0} ${y0}H${x1 - BEND}L${x1} ${y1}`, len: run + BEND * Math.SQRT2 };
  };
  return (
    <div
      ref={box}
      // a scrollable region must be reachable by keyboard (WCAG 2.1.1)
      // biome-ignore lint/a11y/noNoninteractiveTabindex: scrollable region
      tabIndex={scrolls ? 0 : undefined}
      className={cn("overflow-x-auto", className)}
      data-variant={variant}
    >
      <div style={{ width, minWidth: width }}>
        <svg
          role="img"
          aria-label={description}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          width={width}
          height={HEIGHT}
          className="block"
        >
          {steps.map((s, i) => {
            const seg = segment(i);
            const state = s.state ?? "done";
            return (
              <path
                key={`seg-${s.id}`}
                d={seg.d}
                fill="none"
                stroke={state === "pending" ? "var(--color-rule)" : COLOR[s.actor]}
                strokeWidth={state === "pending" ? 1 : 3}
                strokeDasharray={state === "running" ? "7 5" : undefined}
                className={i === drawIndex && state === "done" ? "path-draw" : undefined}
                style={i === drawIndex ? ({ "--len": seg.len } as CSSProperties) : undefined}
              />
            );
          })}
          {steps.map((s, i) => (
            <rect
              key={`node-${s.id}`}
              x={nodeX(i, W) - NODE / 2 + 1.5}
              y={nodeY(i) - NODE / 2 + 1.5}
              width={NODE - 3}
              height={NODE - 3}
              fill="var(--color-sheet)"
              stroke={s.state === "pending" ? "var(--color-ink-soft)" : COLOR[s.actor]}
              strokeWidth={3}
            />
          ))}
          {n > 0 ? (
            <rect
              x={nodeX(n, W) - NODE / 2 - 2}
              y={nodeY(n) - NODE / 2 - 2}
              width={NODE + 4}
              height={NODE + 4}
              fill={complete ? COLOR[steps[n - 1]?.actor ?? "rule"] : "var(--color-sheet)"}
              stroke={complete ? COLOR[steps[n - 1]?.actor ?? "rule"] : "var(--color-ink-soft)"}
              strokeWidth={3}
            />
          ) : null}
        </svg>
        <ol aria-hidden className="flex">
          {steps.map((s) => (
            <li
              key={s.id}
              className="px-1 text-center text-[13px] leading-tight"
              style={{ width: W }}
            >
              {s.label}
              {s.detail ? (
                <span className="mt-0.5 block text-xs text-ink-soft">{s.detail}</span>
              ) : null}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

const MINI_W = 36;

/**
 * Miniature of a run path for choice cards: one row per variant, no labels. Same geometry
 * language as `RunPath` (3px segments bent at 45 degrees, square nodes, filled end).
 */
export function RunPathMini({
  rows,
  description,
  className,
}: {
  /** actors of the stages of each shown path (one row for A or B, two for "both") */
  rows: PathActor[][];
  description: string;
  className?: string;
}) {
  const n = Math.max(...rows.map((r) => r.length));
  const width = (n + 1) * MINI_W;
  const rowH = 30;
  const hi = 6;
  const lo = 18;
  const bend = lo - hi;
  const x = (i: number) => MINI_W / 2 + i * MINI_W;
  const y = (i: number) => (i % 2 === 0 ? lo : hi);
  return (
    <svg
      role="img"
      aria-label={description}
      viewBox={`0 0 ${width} ${rows.length * rowH}`}
      className={cn("block h-auto w-full", className)}
    >
      {rows.map((actors, r) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: fixed decorative rows
        <g key={r} transform={`translate(0 ${r * rowH})`}>
          {actors.map((a, i) => (
            <path
              // biome-ignore lint/suspicious/noArrayIndexKey: fixed decorative sequence
              key={i}
              d={`M${x(i)} ${y(i)}H${x(i + 1) - bend}L${x(i + 1)} ${y(i + 1)}`}
              fill="none"
              stroke={COLOR[a]}
              strokeWidth={3}
            />
          ))}
          {actors.map((a, i) => (
            <rect
              // biome-ignore lint/suspicious/noArrayIndexKey: fixed decorative sequence
              key={i}
              x={x(i) - 4}
              y={y(i) - 4}
              width={8}
              height={8}
              fill="var(--color-sheet)"
              stroke={COLOR[a]}
              strokeWidth={2.5}
            />
          ))}
          <rect
            x={x(actors.length) - 5}
            y={y(actors.length) - 5}
            width={10}
            height={10}
            fill={COLOR[actors[actors.length - 1] ?? "rule"]}
          />
        </g>
      ))}
    </svg>
  );
}
