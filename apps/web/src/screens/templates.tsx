import type { NewRunPreset } from "../lib/layout";

type Template = NonNullable<NewRunPreset["template"]>;

export const TEMPLATES: Record<
  Template,
  { appliedPart: "B" | "BF" | "CF"; power: "battery" | "usb" | "mains"; defib: boolean }
> = {
  ecg: { appliedPart: "BF", power: "battery", defib: true },
  pulseox: { appliedPart: "BF", power: "usb", defib: false },
  eeg: { appliedPart: "CF", power: "battery", defib: false },
  infusion: { appliedPart: "CF", power: "mains", defib: false },
};

/** Small line drawings: a trace or part from each device, on a board-like grid. */
export function TemplateArt({ template }: { template: Template }) {
  const grid = (
    <g stroke="currentColor" strokeOpacity="0.08">
      {[20, 40, 60, 80, 100, 120, 140, 160, 180].map((x) => (
        <line key={`x${x}`} x1={x} y1="0" x2={x} y2="96" />
      ))}
      {[24, 48, 72].map((y) => (
        <line key={`y${y}`} x1="0" y1={y} x2="200" y2={y} />
      ))}
    </g>
  );
  const stroke = {
    fill: "none",
    strokeWidth: 2.5,
    strokeLinecap: "round",
    strokeLinejoin: "round",
  } as const;
  return (
    <svg viewBox="0 0 200 96" aria-hidden className="h-24 w-full text-ink">
      {grid}
      {template === "ecg" ? (
        <path
          {...stroke}
          className="stroke-llm"
          d="M0 60 H52 l6-8 6 8 H86 l5 10 7-52 7 60 5-18 H134 q8-14 16 0 H200"
        />
      ) : null}
      {template === "pulseox" ? (
        <>
          <path {...stroke} className="stroke-ink" d="M60 70 V38 a20 20 0 0 1 40 0 V70" />
          <circle cx="80" cy="44" r="6" className="fill-error/80" />
          <path {...stroke} className="stroke-llm" d="M116 56 q10-24 20 0 t20 0 t20 0" />
        </>
      ) : null}
      {template === "eeg" ? (
        <>
          <path
            {...stroke}
            className="stroke-llm"
            d="M0 30 q10-10 20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0"
          />
          <path
            {...stroke}
            className="stroke-rule"
            d="M0 52 q8 8 16 0 t16 0 t16 0 t16 0 t16 0 t16 0 t16 0 t16 0 t16 0 t16 0 t16 0 t16 0 t16 0"
          />
          <path
            {...stroke}
            className="stroke-ink/60"
            d="M0 74 q12-6 24 0 t24 0 t24 0 t24 0 t24 0 t24 0 t24 0 t24 0 t24 0"
          />
        </>
      ) : null}
      {template === "infusion" ? (
        <>
          <rect x="70" y="14" width="34" height="52" rx="6" {...stroke} className="stroke-ink" />
          <path {...stroke} className="stroke-ink" d="M87 66 V80 H150" />
          <path className="fill-llm" d="M150 70 q6 9 0 14 q-6-5 0-14z" />
        </>
      ) : null}
    </svg>
  );
}
