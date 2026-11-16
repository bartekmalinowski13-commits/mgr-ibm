export type QuotaLevel = "ok" | "warn" | "full";
export const QUOTA_WARN_AT = 0.8;

export function quotaLevel(used: number, limit: number | undefined): QuotaLevel {
  if (!limit || limit <= 0) return "ok";
  const ratio = used / limit;
  if (ratio >= 1) return "full";
  return ratio >= QUOTA_WARN_AT ? "warn" : "ok";
}

export interface QuotaChip {
  key: "runs" | "cost_eur";
  used: number;
  limit: number;
  level: QuotaLevel;
}

/** Metrics that have a plan limit, in display order. */
export function quotaChips(
  usage: Record<string, number>,
  limits: Record<string, number>,
): QuotaChip[] {
  const defs = [
    { key: "runs", limit: limits.max_runs_per_month },
    { key: "cost_eur", limit: limits.llm_budget_eur_per_month },
  ] as const;
  return defs.flatMap((d) =>
    d.limit
      ? [
          {
            key: d.key,
            used: usage[d.key] ?? 0,
            limit: d.limit,
            level: quotaLevel(usage[d.key] ?? 0, d.limit),
          },
        ]
      : [],
  );
}
