import { cn } from "./cn";

export interface TitleBlockCell {
  label: string;
  value: string;
}

/**
 * Drawing title block (ADR-0019) in the bottom-right corner of a sheet: the object's name
 * (Archivo 125/800) and sheet number, then up to six label/value cells (3 × 2).
 */
export function TitleBlock({
  name,
  sheetLabel,
  cells,
  label,
  className,
}: {
  name: string;
  /** e.g. "Arkusz 3 z 4" */
  sheetLabel?: string;
  cells: TitleBlockCell[];
  /** accessible name of the block, e.g. "Tabliczka rysunkowa" */
  label: string;
  className?: string;
}) {
  const shown = cells.slice(0, 6);
  return (
    <section
      aria-label={label}
      className={cn(
        "grid w-full grid-cols-2 border-t border-ink bg-sheet text-left sm:grid-cols-[minmax(180px,auto)_repeat(3,minmax(0,auto))] min-[900px]:w-auto min-[900px]:border-l",
        className,
      )}
    >
      <div className="col-span-2 flex flex-col justify-center border-b border-line px-4 py-3 sm:col-span-1 sm:row-span-2 sm:border-b-0 sm:border-r">
        <p className="font-display text-[24px] leading-tight">{name}</p>
        {sheetLabel ? <p className="text-[14px]">{sheetLabel}</p> : null}
      </div>
      <dl className="contents">
        {shown.map((c, i) => (
          <div
            key={c.label}
            className={cn(
              "min-w-0 border-line px-3.5 py-2",
              i % 3 !== 2 && "sm:border-r",
              i < 3 && "sm:border-b",
              "max-sm:border-b max-sm:odd:border-r",
            )}
          >
            <dt className="text-[12.5px] text-muted">{c.label}</dt>
            <dd className="truncate text-[14px] font-semibold" title={c.value}>
              {c.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
