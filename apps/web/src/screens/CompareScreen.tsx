import { Button, MaskPanel, Select, Silk, StatusBadge, TitleBlock } from "@bomagent/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { api, call, type Schemas, saveBlob } from "../lib/api";
import { formatDuration, formatNumber } from "../lib/format";
import { SheetSlot, usePageTitle } from "../lib/layout";
import { type BomItem, formatEur } from "../lib/provenance";
import { useModelLabel, useProjects, useRuns } from "../lib/queries";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { valuesEquivalent } from "../lib/values";
import { compareRoute } from "../router";
import { LoadError, Skeleton } from "./common";

const FIELDS = ["value", "manufacturer", "mpn"] as const;

interface Diff {
  refdes: string;
  a?: BomItem;
  b?: BomItem;
  changed: (typeof FIELDS)[number][];
}

/** Per designator: what each variant decided, and where they disagree. Values are
 * compared by meaning, not spelling (`100n` = `100 nF`): variant A writes values in
 * canonical form, variant B keeps the schematic's notation. */
export function diffBoms(a: Schemas["BomVersion"], b: Schemas["BomVersion"]): Diff[] {
  const ia = new Map(a.items.flatMap((i) => i.refdes.map((r) => [r, i] as const)));
  const ib = new Map(b.items.flatMap((i) => i.refdes.map((r) => [r, i] as const)));
  const refs = [...new Set([...ia.keys(), ...ib.keys()])].sort((x, y) =>
    x.localeCompare(y, undefined, { numeric: true }),
  );
  return refs.map((refdes) => {
    const x = ia.get(refdes);
    const y = ib.get(refdes);
    const same = (f: (typeof FIELDS)[number]) =>
      f === "value" ? valuesEquivalent(x?.value, y?.value) : (x?.[f] ?? "") === (y?.[f] ?? "");
    const changed = x && y ? FIELDS.filter((f) => !same(f)) : [...FIELDS];
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

export interface VerdictMetrics {
  costA: number;
  costB: number;
  findingsA: number;
  findingsB: number;
  differences: number;
}

/** A cost ratio below this is not worth a headline of its own. */
const COST_RATIO = 1.5;

/** The sheet conclusion, derived only from measured numbers: an i18n key and its params. */
export function verdict(m: VerdictMetrics): { key: string; params: { x?: number } } {
  if (m.differences === 0 && m.findingsA === m.findingsB && m.costA === m.costB)
    return { key: "compare.verdict.same", params: {} };
  if (m.costA > 0 && m.costB > 0) {
    const ratio = m.costA / m.costB;
    if (ratio >= COST_RATIO)
      return { key: "compare.verdict.cheaper", params: { x: Number(ratio.toFixed(1)) } };
    if (1 / ratio >= COST_RATIO)
      return { key: "compare.verdict.pricier", params: { x: Number((1 / ratio).toFixed(1)) } };
  }
  if (m.findingsB < m.findingsA) return { key: "compare.verdict.fewerFindings", params: {} };
  if (m.findingsB > m.findingsA) return { key: "compare.verdict.moreFindings", params: {} };
  if (m.differences === 0) return { key: "compare.verdict.same", params: {} };
  return { key: "compare.verdict.differ", params: {} };
}

type Reason = "mpn" | "onlyA" | "onlyB" | "value" | "manufacturer";

/** The one thing that explains a row; the result badge follows from it. */
function reasonOf(d: Diff): Reason {
  if (!d.a) return "onlyB";
  if (!d.b) return "onlyA";
  if (d.changed.includes("mpn")) return "mpn";
  return d.changed.includes("value") ? "value" : "manufacturer";
}

const csvCell = (v: string | number) => {
  const s = String(v);
  return /[",\n\r;]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
};

function Bars({ a, b }: { a: number; b: number }) {
  const max = Math.max(a, b);
  const w = (v: number) => (max > 0 && v > 0 ? `${Math.max((v / max) * 100, 2)}%` : "0%");
  return (
    <div aria-hidden className="flex min-w-[90px] flex-col gap-1.5">
      {(
        [
          [a, "bg-llm-light"],
          [b, "bg-silk"],
        ] as const
      ).map(([v, color]) => (
        <div key={color} className="h-2 rounded-chip bg-silk/15">
          <div className={`h-full rounded-chip ${color}`} style={{ width: w(v) }} />
        </div>
      ))}
    </div>
  );
}

export function CompareScreen() {
  const { projectId } = compareRoute.useParams();
  const search = compareRoute.useSearch();
  const navigate = useNavigate();
  const toast = useToast();
  const { t, i18n } = useTranslation();
  const modelLabel = useModelLabel();
  usePageTitle(t("compare.title"));
  const runs = useRuns(projectId);
  const projects = useProjects();
  const project = projects.data?.items.find((p) => p.id === projectId);
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
    return <p className="max-w-[70ch] text-muted">{t("compare.needTwo")}</p>;
  // a BOM that failed to load must never read as "no differences" (wrong thesis result)
  const bomError = bomA.isError ? bomA.error : bomB.isError ? bomB.error : undefined;
  const retryBoms = () => {
    if (bomA.isError) void bomA.refetch();
    if (bomB.isError) void bomB.refetch();
  };
  const loading = bomA.isLoading || bomB.isLoading;
  const ready = !bomError && !loading && !!bomA.data && !!bomB.data;

  const pick = (side: "a" | "b", id: string) =>
    void navigate({
      to: "/projects/$projectId/compare",
      params: { projectId },
      search: { a: side === "a" ? id : runA?.id, b: side === "b" ? id : runB?.id },
    });
  const disagree = diffs.filter((d) => d.changed.length);
  const metric = (r: Schemas["Run"] | undefined, key: string) => Number(r?.usage?.[key] ?? 0);
  const num = (v: number) => formatNumber(v, lang);
  const rows = [
    {
      key: "lines",
      label: t("compare.lines"),
      a: bomA.data?.bom.items.length ?? 0,
      b: bomB.data?.bom.items.length ?? 0,
      fmt: num,
    },
    {
      key: "calls",
      label: t("run.llmCalls"),
      a: metric(runA, "llm_calls"),
      b: metric(runB, "llm_calls"),
      fmt: num,
    },
    {
      key: "tokens",
      label: t("run.tokens"),
      a: metric(runA, "input_tokens") + metric(runA, "output_tokens"),
      b: metric(runB, "input_tokens") + metric(runB, "output_tokens"),
      fmt: num,
    },
    {
      key: "cost",
      label: t("run.cost"),
      a: metric(runA, "cost_eur"),
      b: metric(runB, "cost_eur"),
      fmt: (v: number) => formatEur(v, lang),
    },
    {
      key: "findings",
      label: t("compare.findings"),
      a: bomA.data?.bom.findings?.length ?? 0,
      b: bomB.data?.bom.findings?.length ?? 0,
      fmt: num,
    },
  ];
  const byKey = (k: string) => rows.find((r) => r.key === k) ?? { a: 0, b: 0 };
  const v = verdict({
    costA: byKey("cost").a,
    costB: byKey("cost").b,
    findingsA: byKey("findings").a,
    findingsB: byKey("findings").b,
    differences: disagree.length,
  });
  // the user may put any run on either side (B left, A right, or A vs A with two models):
  // every sentence names the sides by their real variant, never by position
  const same = runA.variant === runB.variant;
  const va = same ? `${runA.variant}1` : runA.variant;
  const vb = same ? `${runB.variant}2` : runB.variant;
  const name = (variant: string, label: string, start: boolean) =>
    same
      ? t(start ? "compare.name.runStart" : "compare.name.run", { v: label })
      : t(`compare.name.${variant}${start ? "Start" : ""}`, {
          defaultValue: t(start ? "compare.name.otherStart" : "compare.name.other", { v: variant }),
        });

  const exportCsv = () => {
    const lines: (string | number)[][] = [
      [t("compare.csv.metric"), va, vb],
      ...rows.map((r) => [r.label, r.a, r.b]),
      [],
      [t("compare.csv.designator"), t("compare.csv.field"), va, vb],
      ...disagree.flatMap((d) =>
        (d.changed as readonly (typeof FIELDS)[number][]).map((f) => [
          d.refdes,
          t(`bom.columns.${f}`),
          d.a?.[f] ?? "",
          d.b?.[f] ?? "",
        ]),
      ),
    ];
    const csv = `\uFEFF${lines.map((l) => l.map(csvCell).join(",")).join("\r\n")}\r\n`;
    saveBlob(
      new Blob([csv], { type: "text/csv;charset=utf-8" }),
      `compare-${runA.id.slice(0, 8)}-${runB.id.slice(0, 8)}.csv`,
    );
    toast(t("compare.exported"));
  };

  const differ = (a: string | number, b: string | number) => (a === b ? `${a}` : `${a} / ${b}`);
  const shortIds = `${va} #${runA.id.slice(0, 8)}, ${vb} #${runB.id.slice(0, 8)}`;

  return (
    <>
      <SheetSlot name="crumbs">
        <Link to="/projects" className="hover:text-ink hover:underline">
          {t("compare.projects")}
        </Link>
        <span aria-hidden>/</span>
        {project ? (
          <>
            <Link
              to="/projects/$projectId"
              params={{ projectId }}
              className="hover:text-ink hover:underline"
            >
              {project.name}
            </Link>
            <span aria-hidden>/</span>
          </>
        ) : null}
      </SheetSlot>
      <SheetSlot name="actions">
        <Button variant="secondary" disabled={!ready} onClick={exportCsv}>
          {t("compare.export")}
        </Button>
      </SheetSlot>
      <SheetSlot name="titleBlock">
        <TitleBlock
          label={t("sheet.titleBlock")}
          name={t("compare.blockName")}
          sheetLabel={t("sheet.number", { n: 4, m: 4 })}
          cells={[
            { label: t("titleBlock.project"), value: project?.name ?? "—" },
            { label: t("titleBlock.runs"), value: shortIds },
            {
              label: t("titleBlock.model"),
              value: differ(modelLabel(runA.model_id), modelLabel(runB.model_id)),
            },
            {
              label: t("titleBlock.costAB"),
              value: differ(formatEur(byKey("cost").a, lang), formatEur(byKey("cost").b, lang)),
            },
            {
              label: t("titleBlock.timeAB"),
              value: differ(
                formatDuration(metric(runA, "wall_time_s")),
                formatDuration(metric(runB, "wall_time_s")),
              ),
            },
            { label: t("compare.differencesCell"), value: ready ? num(disagree.length) : "—" },
          ]}
        />
      </SheetSlot>

      <div className="flex flex-col gap-6">
        <div className="grid max-w-[760px] gap-3 sm:grid-cols-2">
          {(["a", "b"] as const).map((side) => (
            <label key={side} className="flex flex-col gap-1.5 text-[14px] text-muted">
              {t(side === "a" ? "compare.left" : "compare.right")}
              <Select
                value={(side === "a" ? runA : runB)?.id ?? ""}
                onChange={(e) => pick(side, e.target.value)}
              >
                {done.map((r) => (
                  <option key={r.id} value={r.id}>
                    {t("run.variant", { variant: r.variant })} – {modelLabel(r.model_id)} –{" "}
                    {r.id.slice(0, 8)}
                  </option>
                ))}
              </Select>
            </label>
          ))}
        </div>

        {bomError ? (
          <LoadError error={bomError} onRetry={retryBoms} />
        ) : (
          <div className="grid items-start gap-8 min-[900px]:grid-cols-[55fr_45fr] min-[900px]:gap-10">
            {loading ? (
              <Skeleton rows={6} />
            ) : (
              <MaskPanel
                aria-labelledby="verdict-title"
                className="min-w-0 px-6 pb-8 pt-14 sm:px-10 sm:pb-10 sm:pt-16"
              >
                <Silk>{t("compare.silk", { project: project?.name ?? "—", a: va, b: vb })}</Silk>
                <h2
                  id="verdict-title"
                  className="mt-3 max-w-[16ch] font-display text-[34px] leading-[1.02] text-silk sm:text-[52px]"
                >
                  {t(v.key, {
                    x: v.params.x === undefined ? undefined : num(v.params.x),
                    right: name(runB.variant, vb, true),
                    left: name(runA.variant, va, false),
                  })}
                </h2>
                <p className="mt-4 max-w-[52ch] text-[16px] leading-relaxed text-silk">
                  {t("compare.lead", {
                    a: va,
                    b: vb,
                    linesA: num(byKey("lines").a),
                    linesB: num(byKey("lines").b),
                    findingsA: num(byKey("findings").a),
                    findingsB: num(byKey("findings").b),
                    costA: formatEur(byKey("cost").a, lang),
                    costB: formatEur(byKey("cost").b, lang),
                  })}
                </p>
                <table className="mt-6 w-full border-collapse text-left">
                  <caption className="sr-only">{t("compare.metrics")}</caption>
                  <thead className="sr-only">
                    <tr>
                      <th scope="col">{t("compare.metric")}</th>
                      <th scope="col">{t("compare.colBars")}</th>
                      <th scope="col">{t("compare.colValues")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.key} className="border-t border-silk/25">
                        <th scope="row" className="py-3 pr-3 text-[15px] font-normal">
                          {r.label}
                        </th>
                        <td className="w-[40%] py-3 pr-3">
                          <Bars a={r.a} b={r.b} />
                        </td>
                        <td className="py-3 text-right font-data text-[14px] leading-[1.35] whitespace-nowrap">
                          <span className="block text-llm-light">
                            {va} {r.fmt(r.a)}
                          </span>
                          <span className="block">
                            {vb} {r.fmt(r.b)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </MaskPanel>
            )}

            <section aria-labelledby="diff-title" className="flex min-w-0 flex-col gap-3">
              <h2 id="diff-title" className="text-[22px] font-semibold">
                {t("compare.differences", { count: disagree.length })}
              </h2>
              {loading ? (
                <Skeleton rows={4} />
              ) : (
                <>
                  <p className="text-muted">
                    {t("compare.differencesLead", { n: disagree.length, total: diffs.length })}
                  </p>
                  {disagree.length === 0 ? (
                    <p className="text-muted">{t("compare.same")}</p>
                  ) : (
                    <section
                      // biome-ignore lint/a11y/noNoninteractiveTabindex: keyboard users must be able to scroll the table
                      tabIndex={0}
                      aria-labelledby="diff-title"
                      className="overflow-x-auto"
                    >
                      <table className="w-full min-w-[460px] border-collapse text-left">
                        <thead className="text-[14px] text-muted">
                          <tr className="border-b border-ink">
                            <th scope="col" className="py-2 pr-3 font-normal">
                              {t("compare.colRefdes")}
                            </th>
                            <th scope="col" className="py-2 pr-3 font-normal">
                              {t("compare.colChoice")}
                            </th>
                            <th scope="col" className="py-2 font-normal">
                              {t("compare.colResult")}
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {disagree.map((d) => (
                            <DiffRow
                              key={d.refdes}
                              d={d}
                              la={va}
                              lb={vb}
                              toneA={runA.variant}
                              toneB={runB.variant}
                            />
                          ))}
                        </tbody>
                      </table>
                    </section>
                  )}
                </>
              )}
            </section>
          </div>
        )}
      </div>
    </>
  );
}

const TONE: Record<string, string> = { A: "text-llm", B: "text-rule" };

function DiffRow({
  d,
  la,
  lb,
  toneA,
  toneB,
}: {
  d: Diff;
  /** labels of the left and right run (their variants) */
  la: string;
  lb: string;
  toneA: string;
  toneB: string;
}) {
  const { t } = useTranslation();
  const reason = reasonOf(d);
  const badge =
    reason === "mpn"
      ? { status: "warn" as const, label: t("compare.result.differ") }
      : reason === "onlyA" || reason === "onlyB"
        ? { status: "warn" as const, label: t(`compare.result.${reason}`, { a: la, b: lb }) }
        : { status: "ok" as const, label: t("compare.result.mpnSame") };
  const field = reason === "manufacturer" ? "manufacturer" : "value";
  return (
    <tr className="border-b border-line align-top">
      <th scope="row" className="py-3 pr-3 font-data text-[15px] font-normal">
        {d.refdes}
      </th>
      <td className="py-3 pr-3">
        <span className={`block font-data text-[14px] ${TONE[toneA] ?? "text-ink"}`}>
          {la} {d.a?.mpn || "—"}
        </span>
        <span className={`block font-data text-[14px] ${TONE[toneB] ?? "text-ink"}`}>
          {lb} {d.b?.mpn || "—"}
        </span>
        <span className="mt-1 block text-[14px] text-muted">
          {t(`compare.reason.${reason}`, {
            a: d.a?.[field] || "—",
            b: d.b?.[field] || "—",
            la,
            lb,
          })}
        </span>
      </td>
      <td className="py-3 whitespace-nowrap">
        <StatusBadge status={badge.status} label={badge.label} />
      </td>
    </tr>
  );
}
