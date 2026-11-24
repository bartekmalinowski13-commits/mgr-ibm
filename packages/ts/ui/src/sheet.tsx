import type { ReactNode } from "react";
import { cn } from "./cn";

const COLUMNS = ["A", "B", "C", "D", "E", "F", "G", "H"] as const;
const ROWS = ["1", "2", "3", "4", "5", "6"] as const;

/** Zone letters (top edge) and numbers (left edge) of a drawing sheet. */
export const SHEET_ZONES = { columns: COLUMNS, rows: ROWS } as const;

/**
 * Drawing sheet (ADR-0019): `sheet` surface with a 1 px ink frame, a second `line` frame 11 px
 * outside it and zones A–H / 1–6 in the gutter. Below 900 px the zone frame is dropped.
 * The title block, when given, sits in the bottom-right corner (under the content on phones).
 */
export function Sheet({
  children,
  titleBlock,
  className,
}: {
  children: ReactNode;
  titleBlock?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative min-[900px]:border min-[900px]:border-line min-[900px]:p-[11px]",
        className,
      )}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-[11px] top-0 hidden h-[11px] grid-cols-8 min-[900px]:grid"
      >
        {COLUMNS.map((c) => (
          <span
            key={c}
            className="border-line font-data text-[9px] leading-[11px] text-muted text-center [&:not(:first-child)]:border-l"
          >
            {c}
          </span>
        ))}
      </div>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-[11px] left-0 hidden w-[11px] grid-rows-6 min-[900px]:grid"
      >
        {ROWS.map((r) => (
          <span
            key={r}
            className="flex items-center justify-center border-line font-data text-[9px] text-muted [&:not(:first-child)]:border-t"
          >
            {r}
          </span>
        ))}
      </div>
      <div className="flex min-h-[calc(100vh-48px-22px)] flex-col border-ink bg-sheet min-[900px]:border">
        <div className="min-w-0 flex-1">{children}</div>
        {titleBlock ? <div className="mt-8 flex justify-end">{titleBlock}</div> : null}
      </div>
    </div>
  );
}

/** Header row of a sheet: breadcrumb/title on the left, actions on the right. */
export function SheetHeader({
  children,
  actions,
  className,
}: {
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-line-soft px-4 py-4 sm:px-10 sm:py-5",
        className,
      )}
    >
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2">{children}</div>
      {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
    </div>
  );
}
