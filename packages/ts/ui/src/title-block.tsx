import { cn } from "./cn";

export interface TitleBlockProps {
  /** project / device name (the big cell) */
  title: string;
  /** revision, already localised, e.g. "Rew. B" */
  revision: string;
  /** run number or short id, e.g. "Przebieg 14" */
  run: string;
  date: string;
  /** "Variant B" / "Wariant B" */
  variant: string;
  /** sheet number, e.g. "1/1" */
  sheet: string;
  /** the word "Sheet" / "Arkusz", last cell */
  sheetLabel: string;
  /** run status text; replaced by the demo flag when `demo` is set */
  status: string;
  /** "Illustrative" / "Poglądowe": set when the data is from a demo deployment */
  demo?: string;
  /** accessible name of the whole block */
  label: string;
  className?: string;
}

/**
 * Drawing title block: 3 columns x 3 rows, 1px ink outline. The only place that shows run
 * metadata. Real data from the run; in demo mode the status cell reads "Illustrative".
 */
export function TitleBlock(p: TitleBlockProps) {
  const cell = "flex min-w-0 items-center border-b border-r border-ink px-2 py-1 text-xs";
  return (
    // biome-ignore lint/a11y/useSemanticElements: a fieldset would be a form group; this is a static labelled block
    <div
      role="group"
      aria-label={p.label}
      data-testid="title-block"
      className={cn(
        "grid w-full max-w-[380px] grid-cols-[1.7fr_1.1fr_1fr] border-l border-t border-ink bg-sheet",
        p.className,
      )}
    >
      <div className={cn(cell, "col-span-2 font-display text-[15px] font-semibold")}>
        <span className="truncate">{p.title}</span>
      </div>
      <div className={cell}>{p.revision}</div>
      <div className={cn(cell, "font-mono")}>{p.run}</div>
      <div className={cn(cell, "font-mono")}>{p.date}</div>
      <div className={cn(cell, p.demo && "font-medium")}>{p.demo ?? p.status}</div>
      <div className={cn(cell, "font-mono")}>{p.sheet}</div>
      <div className={cell}>{p.variant}</div>
      <div className={cell}>{p.sheetLabel}</div>
    </div>
  );
}
