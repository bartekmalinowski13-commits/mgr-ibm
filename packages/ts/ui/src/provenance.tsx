import { cn } from "./cn";

export type Provenance = "agent" | "rule" | "parser" | "user";

const COLOR: Record<Provenance, string> = {
  agent: "text-llm",
  rule: "text-rule",
  parser: "text-parser",
  user: "text-user",
};

/**
 * Who decided, coded by shape and colour (ADR-0019): LLM agent = hollow circle, rule = filled
 * square (pad), parser = outlined diamond, person = filled disc. Decorative unless `label` is set.
 */
export function ProvenanceGlyph({
  kind,
  size = 10,
  label,
  className,
}: {
  kind: Provenance;
  size?: number;
  /** accessible name; without it the glyph is hidden from assistive technology */
  label?: string;
  className?: string;
}) {
  return (
    // biome-ignore lint/a11y/noSvgWithoutTitle: named through aria-label when it carries meaning
    <svg
      viewBox="0 0 10 10"
      width={size}
      height={size}
      className={cn("inline-block shrink-0", COLOR[kind], className)}
      data-provenance={kind}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : "true"}
    >
      {kind === "agent" ? (
        <circle cx="5" cy="5" r="3.6" fill="none" stroke="currentColor" strokeWidth="1.8" />
      ) : null}
      {kind === "rule" ? (
        <rect x="0.8" y="0.8" width="8.4" height="8.4" fill="currentColor" />
      ) : null}
      {kind === "parser" ? (
        <path d="M5 0.9 9.1 5 5 9.1 0.9 5Z" fill="none" stroke="currentColor" strokeWidth="1.2" />
      ) : null}
      {kind === "user" ? <circle cx="5" cy="5" r="4.3" fill="currentColor" /> : null}
    </svg>
  );
}

/** Background class of the 5 px provenance stripe on a BOM row. */
export const PROVENANCE_STRIPE: Record<Provenance, string> = {
  agent: "bg-llm",
  rule: "bg-rule",
  parser: "bg-parser",
  user: "bg-user",
};

/** One-line legend of the four glyphs. */
export function ProvenanceLegend({
  labels,
  className,
}: {
  labels: Record<Provenance, string>;
  className?: string;
}) {
  const order: Provenance[] = ["parser", "rule", "agent", "user"];
  return (
    <ul
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted",
        className,
      )}
    >
      {order.map((k) => (
        <li key={k} className="inline-flex items-center gap-1.5">
          <ProvenanceGlyph kind={k} />
          {labels[k]}
        </li>
      ))}
    </ul>
  );
}
