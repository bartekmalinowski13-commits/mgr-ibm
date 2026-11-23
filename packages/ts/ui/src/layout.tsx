import type { ReactNode } from "react";
import { cn } from "./cn";

/** The grey desk around a white sheet: document screens (BOM, comparison) only. */
export function Desk({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("bg-desk p-3 sm:p-5", className)}>{children}</div>;
}

/** A white sheet with a 1px ink outline. */
export function Sheet({
  children,
  className,
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  return <Tag className={cn("relative border border-ink bg-sheet", className)}>{children}</Tag>;
}

/** Zone frame: numbers 1-6 along the top edge. Brand screen and PDF export only. */
export function ZoneFrame({ zones = 6 }: { zones?: number }) {
  return (
    <div
      aria-hidden
      className="flex h-[18px] border-b border-ink font-sans text-[11px] text-ink-soft"
    >
      {Array.from({ length: zones }, (_, i) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed list of zones
          key={i}
          className="flex-1 border-r border-rule text-center leading-[17px] last:border-r-0"
        >
          {i + 1}
        </span>
      ))}
    </div>
  );
}

/** An empty state always offers a way forward, never a bare "0". */
export function EmptyState({
  title,
  body,
  action,
  className,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn("flex flex-col items-start gap-3 border border-ink bg-sheet p-6", className)}
    >
      <p className="font-display text-xl font-semibold tracking-[-0.01em]">{title}</p>
      {body ? <p className="max-w-[60ch] text-ink-soft">{body}</p> : null}
      {action}
    </div>
  );
}

/** A horizontally scrollable region that keyboard users can reach and scroll (WCAG 2.1.1). */
export function ScrollRegion({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    // biome-ignore lint/a11y/noNoninteractiveTabindex: scrollable region must be focusable
    <section tabIndex={0} aria-label={label} className={cn("overflow-x-auto", className)}>
      {children}
    </section>
  );
}
