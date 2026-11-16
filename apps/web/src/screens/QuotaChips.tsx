import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { formatEur } from "../lib/provenance";
import { type QuotaLevel, quotaChips } from "../lib/quota";
import { useToast } from "../lib/toast";

const TONE: Record<QuotaLevel, string> = {
  ok: "border-line text-muted",
  warn: "border-warn text-warn",
  full: "border-error text-error",
};

/** Read-only usage chips; a toast is raised once per metric when it crosses 80 % and 100 %. */
export function QuotaChips({
  usage,
  limits,
  scope,
}: {
  usage: Record<string, number>;
  limits: Record<string, number>;
  /** Changes with the organisation so a switch re-evaluates the thresholds. */
  scope?: string;
}) {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const chips = quotaChips(usage, limits);
  const lang = i18n.language.startsWith("pl") ? "pl-PL" : "en-GB";
  const told = useRef(new Set<string>());
  const toldScope = useRef(scope);
  if (toldScope.current !== scope) {
    toldScope.current = scope;
    told.current.clear();
  }

  useEffect(() => {
    for (const c of quotaChips(usage, limits)) {
      if (c.level === "ok") continue;
      const id = `${c.key}:${c.level}`;
      if (told.current.has(id)) continue;
      told.current.add(id);
      toast(t(`quota.${c.level}`, { what: t(`quota.names.${c.key}`) }), "error");
    }
  }, [usage, limits, t, toast]);

  if (!chips.length) return null;
  const fmt = (key: string, v: number) => (key === "cost_eur" ? formatEur(v, lang) : String(v));
  return (
    <ul aria-label={t("quota.label")} className="flex flex-wrap items-center gap-1.5 text-sm">
      {chips.map((c) => (
        <li
          key={c.key}
          data-level={c.level}
          className={`rounded-full border bg-surface px-2.5 py-0.5 tabular-nums ${TONE[c.level]}`}
        >
          {t(`quota.${c.key}`, { used: fmt(c.key, c.used), limit: fmt(c.key, c.limit) })}
        </li>
      ))}
    </ul>
  );
}
