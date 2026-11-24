import { cn } from "./cn";
import { ProvenanceGlyph } from "./provenance";

export type Variant = "A" | "B";

/**
 * Variant marker: A (LLM only) = violet with the agent glyph, B (hybrid) = green with the rule
 * glyph. Any other value (e.g. a third, future variant) falls back to a neutral chip.
 */
export function VariantChip({
  variant,
  label,
  className,
}: {
  variant: string;
  /** visible text; defaults to the variant letter */
  label?: string;
  className?: string;
}) {
  const tone =
    variant === "A"
      ? "bg-llm-bg text-llm"
      : variant === "B"
        ? "bg-rule-bg text-rule"
        : "bg-vellum text-ink";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-chip px-2 py-0.5 text-[13px] font-semibold leading-5",
        tone,
        className,
      )}
    >
      {variant === "A" || variant === "B" ? (
        <ProvenanceGlyph kind={variant === "A" ? "agent" : "rule"} size={9} />
      ) : null}
      {label ?? variant}
    </span>
  );
}
