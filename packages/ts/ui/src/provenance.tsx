import { cn } from "./cn";

export type ProvenanceKind = "agent" | "rule" | "parser" | "user";

/**
 * 8px provenance rail on the left of a row or panel title. Double-coded (pattern + colour):
 * LLM agent = hatched violet, rule = solid green, parser = solid grey, person = solid ink.
 * Needs a `relative` parent; the pattern lives in styles.css (`.rail-*`).
 */
export function ProvenanceRail({
  kind,
  label,
  className,
}: {
  kind: ProvenanceKind;
  /** accessible text (e.g. "LLM agent"); the rail itself is decorative */
  label?: string;
  className?: string;
}) {
  return (
    <>
      <span aria-hidden data-provenance={kind} className={cn("rail", `rail-${kind}`, className)} />
      {label ? <span className="sr-only">{label}</span> : null}
    </>
  );
}

/** A small inline swatch with the same pattern: for legends and field lists. */
export function ProvenanceSwatch({
  kind,
  className,
}: {
  kind: ProvenanceKind;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      data-provenance={kind}
      className={cn("inline-block size-3 shrink-0", `rail-${kind}`, className)}
    />
  );
}

/** Variant colours: A = LLM only (violet), B = hybrid (green). Only ever used for provenance. */
export const VARIANT_TEXT = { A: "text-prov-llm", B: "text-prov-rule" } as const;
export const VARIANT_KIND = { A: "agent", B: "rule" } as const;
