import type { ElementType, ReactNode } from "react";
import { cn } from "./cn";

function Hole({ className }: { className: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "absolute size-[22px] rounded-full border-[5px] border-gold bg-silk",
        className,
      )}
    />
  );
}

/**
 * The board panel (ADR-0019): solder-mask green, white silkscreen, gold mounting holes.
 * Only where a conclusion is shown (A/B verdict, part location map). At most one per screen.
 */
export function MaskPanel({
  children,
  as: Tag = "section",
  holes = true,
  className,
  ...rest
}: {
  children: ReactNode;
  as?: ElementType;
  holes?: boolean;
  className?: string;
  "aria-labelledby"?: string;
  "aria-label"?: string;
}) {
  return (
    <Tag
      className={cn(
        "relative rounded-mask bg-mask text-silk",
        "[&_:focus-visible]:outline-gold",
        className,
      )}
      {...rest}
    >
      {holes ? (
        <>
          <Hole className="left-4 top-4" />
          <Hole className="right-4 top-4" />
          <Hole className="bottom-4 left-4" />
          <Hole className="bottom-4 right-4" />
        </>
      ) : null}
      {children}
    </Tag>
  );
}

/** Silkscreen line on the board: the only all-caps text of the product. */
export function Silk({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cn("font-data text-[13px] uppercase tracking-[0.04em] text-gold", className)}>
      {children}
    </p>
  );
}
