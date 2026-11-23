import { Button, ProvenanceSwatch, ScrollRegion, Select, Sheet, VARIANT_TEXT } from "@bomagent/ui";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { FileCheck2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, evaluateRun, problemMessage, type Schemas } from "../lib/api";
import { formatNumber } from "../lib/format";
import { useDeskLayout, usePageTitle } from "../lib/layout";
import { type BomItem, formatEur, lineProvenance } from "../lib/provenance";
import { useProjects, useRuns, useRuntime } from "../lib/queries";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { compareRoute } from "../router";
import { LoadError, Skeleton } from "./common";
import { RunPathPanel } from "./RunPathView";
import { RunTitleBlock } from "./RunTitleBlock";

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
  useDeskLayout();
  const demo = useRuntime().data?.mode === "demo";
  const project = useProjects().data?.items.find((p) => p.id === projectId);
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [reference, setReference] = useState<{
    a: Schemas["Evaluation"];
    b: Schemas["Evaluation"];
  }>();
  const [evaluating, setEvaluating] = useState(false);
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
  if (runs.isError) return <LoadError error={runs.error} onRetry={() => void runs.refetch()} />;
  if (done.length < 2 || !runA || !runB)
    return <p className="max-w-[70ch] text-ink-soft">{t("compare.needTwo")}</p>;
  // a BOM that failed to load must never read as "no differences" (wrong thesis result)
  const bomError = bomA.isError ? bomA.error : bomB.isError ? bomB.error : undefined;
  const retryBoms = () => {
    if (bomA.isError) void bomA.refetch();
    if (bomB.isError) void bomB.refetch();
  };

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

  const evaluate = async (file: File | undefined) => {
    if (!file || !runA || !runB) return;
    setEvaluating(true);
    try {
      const [a, b] = await Promise.all([evaluateRun(runA.id, file), evaluateRun(runB.id, file)]);
      setReference({ a, b });
    } catch (err) {
      toast(problemMessage(err), "error");
    } finally {
      setEvaluating(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };
  const pct = (v: number | null | undefined) =>
    v == null
      ? "–"
      : new Intl.NumberFormat(lang, { style: "percent", maximumFractionDigits: 1 }).format(v);
  const refRows = (
    ["line_f1", "line_precision", "line_recall", "designator_f1", "mpn_coverage"] as const
  ).map((k) => ({
    label: t(`reference.metrics.${k}`),
    a: pct(reference?.a.summary[k]),
    b: pct(reference?.b.summary[k]),
  }));
  const head = (r: Schemas["Run"] | undefined) => `${t("run.variant", { variant: r?.variant })}`;

  return (
    <Sheet className="flex flex-col gap-6 p-5 sm:p-9">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="font-display text-[40px] font-semibold leading-none tracking-[-0.01em]">
          {project ? t("compare.sheetTitle", { project: project.name }) : t("compare.title")}
        </h2>
        <p className="text-ink-soft">{t("compare.lead", { a: runA.variant, b: runB.variant })}</p>
      </div>
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

      <section aria-labelledby="paths-title" className="flex flex-col gap-3">
        <h3 id="paths-title" className="sr-only">
          {t("compare.pathTitle")}
        </h3>
        <div className="grid gap-4 lg:grid-cols-2">
          <RunPathPanel run={runA} />
          <RunPathPanel run={runB} />
        </div>
      </section>

      {bomError ? (
        <LoadError error={bomError} onRetry={retryBoms} />
      ) : (
        <>
          <section aria-labelledby="ref-metrics-title" className="border border-ink">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-ink px-5 py-3.5">
              <h3
                id="ref-metrics-title"
                className="font-display text-2xl font-semibold tracking-[-0.01em]"
              >
                {t("compare.metricsTitle")}
              </h3>
              <div className="flex flex-wrap items-center gap-3">
                {demo ? <p className="text-sm text-ink-soft">{t("demoData")}</p> : null}
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={evaluating}
                  onClick={() => fileInput.current?.click()}
                >
                  <FileCheck2 size={16} aria-hidden /> {t("reference.upload")}
                </Button>
                <input
                  ref={fileInput}
                  type="file"
                  accept=".csv,text/csv"
                  className="sr-only"
                  aria-label={t("reference.upload")}
                  data-testid="compare-reference-input"
                  onChange={(e) => void evaluate(e.target.files?.[0])}
                />
              </div>
            </div>
            {reference ? (
              <MetricTable
                caption={t("compare.metricsTitle")}
                runA={runA}
                runB={runB}
                rows={refRows}
              />
            ) : (
              <p className="max-w-[70ch] px-5 py-4 text-ink-soft">{t("compare.referenceNone")}</p>
            )}
          </section>

          <section aria-labelledby="run-metrics-title" className="border border-ink">
            <div className="border-b border-ink px-5 py-3.5">
              <h3
                id="run-metrics-title"
                className="font-display text-2xl font-semibold tracking-[-0.01em]"
              >
                {t("compare.metrics")}
              </h3>
            </div>
            <MetricTable
              caption={t("compare.metrics")}
              runA={runA}
              runB={runB}
              rows={rows.map((r) => ({ label: r.label, a: r.fmt(r.a), b: r.fmt(r.b) }))}
            />
          </section>

          <section aria-labelledby="diff-title" className="flex flex-col gap-3">
            <h3 id="diff-title" className="font-display text-2xl font-semibold tracking-[-0.01em]">
              {t("compare.differences", { count: disagree.length })}
            </h3>
            {bomA.isLoading || bomB.isLoading ? (
              <Skeleton rows={4} />
            ) : disagree.length === 0 ? (
              <p className="text-ink-soft">{t("compare.same")}</p>
            ) : (
              <ScrollRegion
                label={t("compare.differences", { count: disagree.length })}
                className="border border-ink"
              >
                <table className="w-full min-w-[720px] text-left text-[14px]">
                  <thead className="border-b border-ink text-[13px] text-ink-soft">
                    <tr>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t("bom.columns.refdes")}
                      </th>
                      <th
                        scope="col"
                        className={`px-3 py-2 font-semibold ${VARIANT_TEXT[runA.variant === "A" ? "A" : "B"]}`}
                      >
                        {head(runA)}
                      </th>
                      <th
                        scope="col"
                        className={`px-3 py-2 font-semibold ${VARIANT_TEXT[runB.variant === "A" ? "A" : "B"]}`}
                      >
                        {head(runB)}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {disagree.map((d) => (
                      <tr key={d.refdes} className="border-b border-rule align-top last:border-0">
                        <th scope="row" className="px-3 py-2.5 font-mono text-[13px] font-normal">
                          {d.refdes}
                        </th>
                        {[d.a, d.b].map((item, i) => (
                          // biome-ignore lint/suspicious/noArrayIndexKey: two fixed columns
                          <td key={i} className="px-3 py-2.5">
                            {item ? (
                              <div className="flex gap-2">
                                <span className="mt-1">
                                  <ProvenanceSwatch kind={lineProvenance(item)} />
                                </span>
                                <dl className="grid grid-cols-[auto_1fr] gap-x-3">
                                  {FIELDS.map((f) => (
                                    <div key={f} className="contents">
                                      <dt className="text-ink-soft">{t(`bom.columns.${f}`)}</dt>
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
                              <span className="text-ink-soft">{t("compare.missing")}</span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollRegion>
            )}
          </section>
          <RunTitleBlock
            run={runA}
            version={bomA.data?.version ?? 1}
            variantLabel={t("compare.variantsBoth", { a: runA.variant, b: runB.variant })}
          />
        </>
      )}
    </Sheet>
  );
}

/** Metrics rows against the two variants: A and B in their provenance colours, values in mono. */
function MetricTable({
  caption,
  runA,
  runB,
  rows,
}: {
  caption: string;
  runA: Schemas["Run"];
  runB: Schemas["Run"];
  rows: { label: string; a: string; b: string }[];
}) {
  const { t } = useTranslation();
  const col = (r: Schemas["Run"]) => VARIANT_TEXT[r.variant === "A" ? "A" : "B"];
  return (
    <ScrollRegion label={caption}>
      <table className="w-full min-w-[480px] text-left">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-ink text-[13px] font-semibold">
          <tr>
            <th scope="col" className="px-5 py-2 font-medium text-ink-soft">
              {t("compare.metric")}
            </th>
            <th scope="col" className={`px-5 py-2 ${col(runA)}`}>
              {t("run.variant", { variant: runA.variant })}
            </th>
            <th scope="col" className={`px-5 py-2 ${col(runB)}`}>
              {t("run.variant", { variant: runB.variant })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-b border-rule last:border-0">
              <th scope="row" className="px-5 py-2.5 font-normal">
                {r.label}
              </th>
              <td className="px-5 py-2.5 font-mono text-[14px] tabular-nums">{r.a}</td>
              <td className="px-5 py-2.5 font-mono text-[14px] tabular-nums">{r.b}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}
