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

/**
 * Line drawings of the template devices (ADR-0019): 1.4 px ink stroke, no fill, rounded
 * joins, exactly one solid element per drawing.
 */
export function TemplateArt({ template }: { template: Template }) {
  const line = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.4,
    strokeLinecap: "round",
    strokeLinejoin: "round",
  } as const;
  return (
    <svg viewBox="0 0 120 80" aria-hidden className="h-20 w-[120px] text-ink">
      <g {...line}>
        {template === "ecg" ? (
          <>
            <rect x="38" y="6" width="44" height="38" rx="7" />
            <rect x="44" y="12" width="26" height="16" rx="2" />
            <path d="M46 21 h5 l2-4 3 8 2-4 h12" />
            <path d="M50 44 C50 58 36 54 26 66" />
            <path d="M60 44 V67" />
            <path d="M70 44 C70 58 84 54 94 66" />
            <circle cx="24" cy="69" r="3" />
            <circle cx="60" cy="70" r="3" />
            <circle cx="96" cy="69" r="3" />
            <path d="M46 36 h14" />
          </>
        ) : null}
        {template === "pulseox" ? (
          <>
            <rect x="14" y="20" width="80" height="18" rx="9" />
            <rect x="14" y="43" width="80" height="16" rx="8" />
            <rect x="50" y="25" width="24" height="7" rx="2" />
            <path d="M6 40.5 H100" strokeDasharray="3 3" />
            <path d="M94 29 L108 22 M94 51 L108 58" />
          </>
        ) : null}
        {template === "eeg" ? (
          <>
            <rect x="8" y="28" width="104" height="42" rx="3" />
            {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
              <circle key={i} cx={22 + i * 11.5} cy="40" r="3.6" />
            ))}
            <rect x="16" y="54" width="32" height="8" rx="1.5" />
            <path d="M32 28 V10 M27 10 H37" />
            <circle cx="96" cy="58" r="6" />
          </>
        ) : null}
        {template === "infusion" ? (
          <>
            <rect x="28" y="6" width="50" height="10" rx="2" />
            <path d="M28 11 H14 M78 11 H100 M100 6 V16 M46 6 V16 M58 6 V16" />
            <rect x="22" y="24" width="76" height="50" rx="5" />
            <rect x="30" y="32" width="36" height="18" rx="2" />
            <path d="M35 39 h14 M35 44 h8" />
            <circle cx="82" cy="42" r="8" />
            <path d="M32 62 h10 M48 62 h10" />
          </>
        ) : null}
      </g>
      {template === "ecg" ? <circle cx="75" cy="19" r="3" fill="currentColor" /> : null}
      {template === "pulseox" ? <circle cx="32" cy="51" r="3.4" fill="currentColor" /> : null}
      {template === "eeg" ? <circle cx="96" cy="58" r="3.2" fill="currentColor" /> : null}
      {template === "infusion" ? <circle cx="82" cy="42" r="3.6" fill="currentColor" /> : null}
    </svg>
  );
}
