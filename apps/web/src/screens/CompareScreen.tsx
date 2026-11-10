import { Select } from "@bomagent/ui";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { api, call, type Schemas } from "../lib/api";
import { formatNumber } from "../lib/format";
import { usePageTitle } from "../lib/layout";
import { type BomItem, formatEur, lineProvenance, PROVENANCE_COLOR } from "../lib/provenance";
import { useRuns } from "../lib/queries";
import { useSession } from "../lib/session";
import { compareRoute } from "../router";
import { LoadError, Skeleton } from "./common";

const FIELDS = ["value", "manufacturer", "mpn"] as const;

interface Diff {
  refdes: string;
  a?: BomItem;
  b?: BomItem;
  changed: (typeof FIELDS)[number][];
}

/** Per designator: what each variant decided, and where they disagree. */
export function diffBoms(a: Schemas["BomVersion"], b: Schemas["BomVersion"]): Diff[] {
  const ia = new Map(a.items.flatMap((i) => i.refdes.map((r) => [r, i] as const)));
  const ib = new Map(b.items.flatMap((i) => i.refdes.map((r) => [r, i] as const)));
  const refs = [...new Set([...ia.keys(), ...ib.keys()])].sort((x, y) =>
    x.localeCompare(y, undefined, { numeric: true }),
  );
  return refs.map((refdes) => {
    const x = ia.get(refdes);
    const y = ib.get(refdes);
    const changed = x && y ? FIELDS.filter((f) => (x[f] ?? "") !== (y[f] ?? "")) : [...FIELDS];
    return { refdes, a: x, b: y, changed };
  });
}

function useBom(runId: string | undefined) {
  const { orgId } = useSession();
  return useQuery({
    queryKey: ["bom", orgId, runId],
    queryFn: () =>
      call(api.GET("/v1/runs/{run_id}/bom", { params: { path: { run_id: runId ?? "" } } })),
    enabled: !!runId,
  });
}

export function CompareScreen() {
  const { projectId } = compareRoute.useParams();
  const search = compareRoute.useSearch();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  usePageTitle(t("compare.title"));
  const runs = useRuns(projectId);
  const done = (runs.data?.items ?? []).filter((r) => r.status === "completed");
  const runA = done.find((r) => r.id === search.a) ?? done.find((r) => r.variant === "A");
  const runB = done.find((r) => r.id === search.b) ?? done.find((r) => r.variant === "B");
  const bomA = useBom(runA?.id);
  const bomB = useBom(runB?.id);
  const diffs = useMemo(
    () => (bomA.data && bomB.data ? diffBoms(bomA.data.bom, bomB.data.bom) : []),
    [bomA.data, bomB.data],
  );
  const lang = i18n.language;

  if (runs.isPending) return <Skeleton />;
  if (runs.isError) return <LoadError error={runs.error} />;
  if (done.length < 2) return <p className="max-w-[70ch] text-muted">{t("compare.needTwo")}</p>;

  const pick = (side: "a" | "b", id: string) =>
    void navigate({
      to: "/projects/$projectId/compare",
      params: { projectId },
      search: { a: side === "a" ? id : runA?.id, b: side === "b" ? id : runB?.id },
    });
  const disagree = diffs.filter((d) => d.changed.length);
  const metric = (r: Schemas["Run"] | undefined, key: string) => Number(r?.usage?.[key] ?? 0);
  const rows = [
    {
      label: t("compare.lines"),
      a: bomA.data?.bom.items.length ?? 0,
      b: bomB.data?.bom.items.length ?? 0,
      fmt: (v: number) => formatNumber(v, lang),
    },
    {
      label: t("run.llmCalls"),
      a: metric(runA, "llm_calls"),
      b: metric(runB, "llm_calls"),
      fmt: (v: number) => formatNumber(v, lang),
    },
    {
      label: t("run.tokens"),
      a: metric(runA, "input_tokens") + metric(runA, "output_tokens"),
      b: metric(runB, "input_tokens") + metric(runB, "output_tokens"),
      fmt: (v: number) => formatNumber(v, lang),
    },
    {
      label: t("run.cost"),
      a: metric(runA, "cost_eur"),
      b: metric(runB, "cost_eur"),
      fmt: (v: number) => formatEur(v, lang),
    },
    {
      label: t("compare.findings"),
      a: bomA.data?.bom.findings?.length ?? 0,
      b: bomB.data?.bom.findings?.length ?? 0,
      fmt: (v: number) => formatNumber(v, lang),
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-3 sm:grid-cols-2">
        {(["a", "b"] as const).map((side) => (
          <label key={side} className="flex flex-col gap-1.5 font-medium">
            {t(side === "a" ? "compare.left" : "compare.right")}
            <Select
              value={(side === "a" ? runA : runB)?.id ?? ""}
              onChange={(e) => pick(side, e.target.value)}
            >
              {done.map((r) => (
                <option key={r.id} value={r.id}>
                  {t("run.variant", { variant: r.variant })} – {r.model_id} – {r.id.slice(0, 8)}
                </option>
              ))}
            </Select>
          </label>
        ))}
      </div>

      <div className="overflow-x-auto rounded-card border border-line bg-surface">
        <table className="w-full min-w-[480px] text-left">
          <caption className="sr-only">{t("compare.metrics")}</caption>
          <thead className="border-b border-line text-sm text-muted">
            <tr>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("compare.metric")}
              </th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("run.variant", { variant: runA?.variant })}
              </th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("run.variant", { variant: runB?.variant })}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-b border-line last:border-0">
                <th scope="row" className="px-4 py-2.5 font-normal">
                  {r.label}
                </th>
                <td className="px-4 py-2.5 font-display text-lg font-bold tabular-nums">
                  {r.fmt(r.a)}
                </td>
                <td className="px-4 py-2.5 font-display text-lg font-bold tabular-nums">
                  {r.fmt(r.b)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section aria-labelledby="diff-title" className="flex flex-col gap-3">
        <h2 id="diff-title" className="font-display text-2xl font-bold">
          {t("compare.differences", { count: disagree.length })}
        </h2>
        {bomA.isPending || bomB.isPending ? (
          <Skeleton rows={4} />
        ) : disagree.length === 0 ? (
          <p className="text-muted">{t("compare.same")}</p>
        ) : (
          <div className="overflow-x-auto rounded-card border border-line bg-surface">
            <table className="w-full min-w-[720px] text-left text-[14px]">
              <thead className="border-b border-line text-[13px] text-muted">
                <tr>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    {t("bom.columns.refdes")}
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    {t("run.variant", { variant: runA?.variant })}
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    {t("run.variant", { variant: runB?.variant })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {disagree.map((d) => (
                  <tr key={d.refdes} className="border-b border-line align-top last:border-0">
                    <th scope="row" className="px-3 py-2.5 font-mono text-[13px] font-normal">
                      {d.refdes}
                    </th>
                    {[d.a, d.b].map((item, i) => (
                      // biome-ignore lint/suspicious/noArrayIndexKey: two fixed columns
                      <td key={i} className="px-3 py-2.5">
                        {item ? (
                          <div className="flex gap-2">
                            <span
                              aria-hidden
                              className={`mt-1.5 size-2.5 shrink-0 rounded-full ${PROVENANCE_COLOR[lineProvenance(item)]}`}
                            />
                            <dl className="grid grid-cols-[auto_1fr] gap-x-3">
                              {FIELDS.map((f) => (
                                <div key={f} className="contents">
                                  <dt className="text-muted">{t(`bom.columns.${f}`)}</dt>
                                  <dd
                                    className={`${f === "mpn" ? "font-mono text-[13px]" : ""} ${d.changed.includes(f) ? "font-semibold" : ""}`}
                                  >
                                    {item[f] || "–"}
                                  </dd>
                                </div>
                              ))}
                            </dl>
                          </div>
                        ) : (
                          <span className="text-muted">{t("compare.missing")}</span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
