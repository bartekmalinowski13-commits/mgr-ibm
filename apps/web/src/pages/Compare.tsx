import { useQuery } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import type { BomVersion, Run, RunTrace } from "../api/types";
import { VariantBadge } from "../components/RunStatus";
import { Card, EmptyState, Mono, PageHeader, Skeleton, TableScroll } from "../components/ui";
import { formatNumber, formatSeconds, isSimulatedModel } from "../lib/format";
import { useApp } from "../state";

interface Side {
  run: Run;
  bom: BomVersion;
  trace: RunTrace;
}

/** Latest finished A and B runs on the same design, unless the URL names them. */
export function pickPair(runs: Run[], a?: string, b?: string): [Run, Run] | null {
  const done = runs.filter((r) => r.status === "completed");
  const runA = a ? done.find((r) => r.id === a) : undefined;
  const runB = b ? done.find((r) => r.id === b) : undefined;
  if (runA && runB) return [runA, runB];
  for (const anchor of runA ? [runA] : runB ? [runB] : done) {
    const wantA = !anchor.variant.startsWith("A");
    const partner = done.find(
      (r) =>
        r.design_id === anchor.design_id &&
        r.variant.startsWith("A") === wantA &&
        r.id !== anchor.id,
    );
    if (partner) return wantA ? [partner, anchor] : [anchor, partner];
  }
  return null;
}

function fieldShare(bom: BomVersion, kind: "agent" | "rule"): number {
  let total = 0;
  let hits = 0;
  for (const item of bom.items) {
    for (const p of Object.values(item.provenance)) {
      total += 1;
      if (p.kind === kind) hits += 1;
    }
  }
  return total ? hits / total : 0;
}

function percent(x: number): string {
  return `${Math.round(x * 100)}%`;
}

function Bar({ value, max, tone }: { value: number; max: number; tone: string }) {
  const width = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <span className="mt-1 block h-1.5 w-full rounded-full bg-paper" aria-hidden>
      <span
        className="block h-full rounded-full"
        style={{ width: `${width}%`, background: tone }}
      />
    </span>
  );
}

export function ComparePage() {
  const { t } = useTranslation();
  const { a, b } = useSearch({ from: "/shell/compare" });
  const { api, orgId } = useApp();
  const runs = useQuery({ queryKey: [orgId, "runs"], queryFn: () => api.listRuns() });
  const pair = runs.data ? pickPair(runs.data.items, a, b) : null;
  const sides = useQuery({
    queryKey: [orgId, "compare", pair?.[0].id, pair?.[1].id],
    enabled: pair != null,
    queryFn: async (): Promise<[Side, Side]> => {
      if (!pair) throw new Error("no pair");
      const load = async (run: Run): Promise<Side> => ({
        run,
        bom: await api.getBom(run.id),
        trace: await api.getTrace(run.id),
      });
      const [sa, sb] = await Promise.all([load(pair[0]), load(pair[1])]);
      return [sa, sb];
    },
  });

  // a just-started pair: wait for both runs, they finish within seconds
  const pending = (runs.data?.items ?? []).filter(
    (r) => (r.id === a || r.id === b) && r.status !== "completed",
  );

  return (
    <>
      <PageHeader title={t("compare.title")} lead={t("compare.lead")} />
      {runs.isPending || (pair && sides.isPending) || (!pair && pending.length > 0) ? (
        <Skeleton className="h-72" />
      ) : !pair ? (
        <EmptyState>{a || b ? t("cmp.pick") : t("cmp.none")}</EmptyState>
      ) : sides.isError || !sides.data ? (
        <EmptyState>{sides.error?.message ?? t("cmp.pick")}</EmptyState>
      ) : (
        <CompareView sides={sides.data} />
      )}
      {pending.length > 0 && <AutoRefresh />}
    </>
  );
}

function AutoRefresh() {
  const { api, orgId } = useApp();
  useQuery({ queryKey: [orgId, "runs"], queryFn: () => api.listRuns(), refetchInterval: 700 });
  return null;
}

function CompareView({ sides }: { sides: [Side, Side] }) {
  const { t } = useTranslation();
  const [A, B] = sides;
  const simulated = isSimulatedModel(A.run.model_id) || isSimulatedModel(B.run.model_id);
  const serious = (bom: BomVersion) =>
    bom.findings.filter((f) => f.severity === "error" || f.severity === "warning").length;

  const rows: Array<{
    label: string;
    a: number;
    b: number;
    fmt: (n: number) => string;
    lowerIsBetter?: boolean;
  }> = [
    { label: t("cmp.lines"), a: A.bom.items.length, b: B.bom.items.length, fmt: formatNumber },
    {
      label: t("cmp.llmCalls"),
      a: A.trace.usage.llm_calls,
      b: B.trace.usage.llm_calls,
      fmt: formatNumber,
      lowerIsBetter: true,
    },
    {
      label: t("cmp.tokensIn"),
      a: A.trace.usage.input_tokens,
      b: B.trace.usage.input_tokens,
      fmt: formatNumber,
      lowerIsBetter: true,
    },
    {
      label: t("cmp.tokensOut"),
      a: A.trace.usage.output_tokens,
      b: B.trace.usage.output_tokens,
      fmt: formatNumber,
      lowerIsBetter: true,
    },
    {
      label: t("cmp.time"),
      a: A.trace.usage.wall_time_s,
      b: B.trace.usage.wall_time_s,
      fmt: formatSeconds,
      lowerIsBetter: true,
    },
    { label: t("cmp.findings"), a: serious(A.bom), b: serious(B.bom), fmt: formatNumber },
    {
      label: t("cmp.byAgent"),
      a: fieldShare(A.bom, "agent"),
      b: fieldShare(B.bom, "agent"),
      fmt: percent,
    },
    {
      label: t("cmp.byRule"),
      a: fieldShare(A.bom, "rule"),
      b: fieldShare(B.bom, "rule"),
      fmt: percent,
    },
  ];

  const keyOf = (refdes: string[]) => [...refdes].sort().join(",");
  const bByRef = new Map(B.bom.items.map((i) => [keyOf(i.refdes), i]));
  const compared = A.bom.items.filter((i) => bByRef.has(keyOf(i.refdes)));
  const diffs = compared.filter((i) => (bByRef.get(keyOf(i.refdes))?.mpn ?? "") !== i.mpn);
  const agreement = compared.length ? (compared.length - diffs.length) / compared.length : 0;

  return (
    <div className="flex flex-col gap-6">
      {simulated && (
        <p className="rounded-[var(--radius-control)] border border-warn/30 bg-warn-bg px-4 py-2.5 text-[13px] text-warn">
          {t("compare.simulated")}
        </p>
      )}
      <TableScroll label={t("compare.title")}>
        <table className="w-full min-w-[620px] text-left text-[13.5px]">
          <thead>
            <tr className="border-b border-line text-[12.5px] text-muted">
              <th scope="col" className="px-5 py-3 font-medium">
                {t("compare.metric")}
              </th>
              {[A, B].map((s) => (
                <th key={s.run.id} scope="col" className="w-[30%] px-5 py-3 font-medium">
                  <Link
                    to="/runs/$runId"
                    params={{ runId: s.run.id }}
                    className="inline-flex items-center gap-2 text-ink underline-offset-2 hover:underline"
                  >
                    <VariantBadge variant={s.run.variant} />
                    {s.run.variant.startsWith("A") ? t("cmp.variantA") : t("cmp.variantB")}
                  </Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const max = Math.max(row.a, row.b);
              const better =
                row.lowerIsBetter && row.a !== row.b ? (row.a < row.b ? "a" : "b") : null;
              return (
                <tr key={row.label} className="border-b border-line last:border-b-0">
                  <th scope="row" className="px-5 py-3 font-normal text-ink-soft">
                    {row.label}
                  </th>
                  {(["a", "b"] as const).map((side) => (
                    <td key={side} className="px-5 py-3">
                      <span className="flex items-baseline gap-2">
                        <span className="font-[family-name:var(--font-mono)] text-[14.5px]">
                          {row.fmt(row[side])}
                        </span>
                        {better === side && (
                          <span className="text-[11.5px] font-semibold text-ok">
                            {t("compare.better")}
                          </span>
                        )}
                      </span>
                      <Bar
                        value={row[side]}
                        max={max}
                        tone={side === "a" ? "var(--color-llm)" : "var(--color-rule)"}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
            <tr>
              <th scope="row" className="px-5 py-3 font-normal text-ink-soft">
                {t("cmp.agreement")}
              </th>
              <td
                colSpan={2}
                className="px-5 py-3 font-[family-name:var(--font-mono)] text-[14.5px]"
              >
                {percent(agreement)}
              </td>
            </tr>
          </tbody>
        </table>
      </TableScroll>

      <section>
        <h2 className="mb-2 text-[16px] font-semibold">{t("cmp.diffs")}</h2>
        {diffs.length === 0 ? (
          <EmptyState>{t("cmp.noDiffs")}</EmptyState>
        ) : (
          <Card>
            <ul>
              {diffs.map((i) => (
                <li
                  key={i.line}
                  className="grid grid-cols-[120px_1fr_1fr] gap-4 border-t border-line px-5 py-3 first:border-t-0"
                >
                  <span className="font-medium">{i.refdes.join(", ")}</span>
                  <Mono>{i.mpn || "–"}</Mono>
                  <Mono>{bByRef.get(keyOf(i.refdes))?.mpn || "–"}</Mono>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>
    </div>
  );
}
