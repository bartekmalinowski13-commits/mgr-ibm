import { cn } from "./cn";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  /** optional count shown after the label, in mono */
  count?: number;
}

/** Joined buttons sharing 1px borders (BOM filters). A toggle group: aria-pressed on each. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** accessible name of the group */
  label: string;
}) {
  return (
    <fieldset className="m-0 inline-flex min-w-0 flex-wrap border-0 p-0">
      <legend className="sr-only">{label}</legend>
      {options.map((o, i) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex h-9 items-center gap-1.5 border border-ink px-3.5 text-[13.5px] font-medium",
              i > 0 && "-ml-px",
              active ? "bg-ink text-sheet" : "bg-sheet text-ink hover:bg-tint",
            )}
          >
            {o.label}
            {o.count !== undefined ? (
              <span className="font-mono text-[12.5px]">{o.count}</span>
            ) : null}
          </button>
        );
      })}
    </fieldset>
  );
}
