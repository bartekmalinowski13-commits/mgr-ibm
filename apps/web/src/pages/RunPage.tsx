import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { clsx } from "clsx";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import type { BomItem, BomVersion, Finding, Provenance, RunTrace, TraceStep } from "../api/types";
import { RunStatus, VariantBadge } from "../components/RunStatus";
import {
  Button,
  Card,
  EmptyState,
  Mono,
  PageHeader,
  PROV_STRIPE,
  ProvChip,
  SeverityChip,
  Skeleton,
  TableScroll,
} from "../components/ui";
import { findingsByLine, lineProvenance, shortFootprint, toCsv, worstSeverity } from "../lib/bom";
import { formatNumber, formatSeconds, isSimulatedModel, modelLabel } from "../lib/format";
import { ruleTitle } from "../lib/rules";
import { useApp } from "../state";

function Steps({ trace, running }: { trace: TraceStep[]; running: boolean }) {
  const { t } = useTranslation();
  if (!trace.length && !running)
    return <p className="text-[13px] text-muted">{t("runPage.noTrace")}</p>;
  return (
    <ol className="flex flex-wrap items-stretch gap-2">
      {trace.map((s, i) => {
        const llm = s.kind === "llm";
        return (
          <li
            // biome-ignore lint/suspicious/noArrayIndexKey: steps can repeat (validate/repair loops)
            key={`${s.step}-${i}`}
            className="flex min-w-[150px] flex-1 flex-col gap-1 rounded-[10px] border-t-[3px] bg-paper px-3 py-2.5"
            style={{ borderTopColor: llm ? "var(--color-llm)" : "var(--color-rule)" }}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="text-[13.5px] font-semibold">{s.step}</span>
              <ProvChip kind={llm ? "agent" : s.kind === "parser" ? "parser" : "rule"} />
            </span>
            <span className="text-[12.5px] leading-snug text-muted">{s.summary}</span>
            <span className="mt-auto font-[family-name:var(--font-mono)] text-[11.5px] text-muted">
              {formatSeconds(s.duration_s)}
              {s.llm_calls > 0 && ` · ${s.llm_calls}× LLM`}
              {s.status !== "ok" && <span className="text-err"> · {s.status}</span>}
            </span>
          </li>
        );
      })}
      {running && (
        <li className="flex min-w-[150px] flex-1 flex-col gap-2 rounded-[10px] border-t-[3px] border-line-strong bg-paper px-3 py-2.5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-3 w-32" />
        </li>
      )}
    </ol>
  );
}

function UsageBar({ trace }: { trace: RunTrace }) {
  const { t } = useTranslation();
  const u = trace.usage;
  const items = [
    [t("run.calls"), formatNumber(u.llm_calls)],
    [t("run.tokens"), `${formatNumber(u.input_tokens)} / ${formatNumber(u.output_tokens)}`],
    [t("run.time"), formatSeconds(u.wall_time_s)],
    [t("runPage.cost"), `${u.cost_eur.toFixed(2)} €`],
  ];
  return (
    <dl className="flex flex-wrap gap-x-6 gap-y-2">
      {items.map(([label, value]) => (
        <div key={label} className="flex items-baseline gap-1.5">
          <dt className="text-[12px] text-muted">{label}</dt>
          <dd className="font-[family-name:var(--font-mono)] text-[13.5px]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ProvenanceDetail({ field, p }: { field: string; p: Provenance }) {
  const { t } = useTranslation();
  const who =
    p.kind === "agent"
      ? `${p.agent} · ${p.prompt_id}@${p.prompt_version}`
      : p.kind === "rule"
        ? `${p.rule_id} · ${p.rule_pack}@${p.rule_pack_version}`
        : p.kind === "parser"
          ? p.parser
          : p.user_id;
  return (
    <li className="border-t border-line py-3 first:border-t-0">
      <div className="flex items-center justify-between gap-2">
        <Mono>{field}</Mono>
        <ProvChip kind={p.kind} />
      </div>
      {who && <p className="mt-1 text-[12.5px] text-muted">{who}</p>}
      {p.rationale && <p className="mt-1 text-[13px]">{p.rationale}</p>}
      {p.citations.length > 0 && (
        <div className="mt-2">
          <p className="text-[12px] text-muted">{t("bom.citations")}</p>
          <ul className="mt-1 flex flex-col gap-1">
            {p.citations.map((c) => (
              <li key={c.chunk_id} className="rounded-md bg-paper px-2 py-1.5 text-[12.5px]">
                {c.quote}
                {c.page != null && <span className="text-muted"> · s. {c.page}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

interface EditValues {
  mpn: string;
  manufacturer: string;
  dnp: boolean;
  note: string;
  remember: boolean;
}

function EditLine({ runId, item }: { runId: string; item: BomItem }) {
  const { t } = useTranslation();
  const { api, orgId, notify } = useApp();
  const qc = useQueryClient();
  const { register, handleSubmit, formState, reset } = useForm<EditValues>({
    defaultValues: {
      mpn: item.mpn,
      manufacturer: item.manufacturer,
      dnp: item.dnp,
      note: "",
      remember: false,
    },
  });
  const save = useMutation({
    mutationFn: (v: EditValues) =>
      api.editBomItem(runId, item.line, {
        mpn: v.mpn.trim() !== item.mpn ? v.mpn.trim() : undefined,
        manufacturer:
          v.manufacturer.trim() !== item.manufacturer ? v.manufacturer.trim() : undefined,
        dnp: v.dnp !== item.dnp ? v.dnp : undefined,
        note: v.note.trim(),
        remember: v.remember,
      }),
    onSuccess: async (bom) => {
      qc.setQueryData([orgId, "bom", runId], bom);
      notify(t("review.saved"));
      reset({ ...formState.defaultValues, note: "", remember: false } as EditValues);
      await qc.invalidateQueries({ queryKey: [orgId, "run", runId] });
      await qc.invalidateQueries({ queryKey: [orgId, "kb"] });
    },
  });
  const field =
    "h-9 w-full rounded-[var(--radius-control)] border border-line bg-paper px-3 text-[13.5px] focus:border-ink focus:bg-surface focus:outline-none";
  return (
    <form onSubmit={handleSubmit((v) => save.mutate(v))} className="flex flex-col gap-3" noValidate>
      <p className="text-[12.5px] text-muted">{t("review.lead")}</p>
      <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
        {t("review.mpn")}
        <input
          className={`${field} font-[family-name:var(--font-mono)]`}
          {...register("mpn", { maxLength: 80 })}
        />
      </label>
      <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
        {t("review.manufacturer")}
        <input className={field} {...register("manufacturer", { maxLength: 120 })} />
      </label>
      <label className="flex items-center gap-2 text-[13px]">
        <input type="checkbox" className="size-4 accent-[var(--color-ink)]" {...register("dnp")} />
        {t("review.dnp")}
      </label>
      <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
        {t("review.note")}*
        <input
          className={field}
          aria-invalid={formState.errors.note ? true : undefined}
          aria-describedby={formState.errors.note ? `note-error-${item.line}` : undefined}
          {...register("note", {
            required: true,
            validate: (v) => v.trim().length > 0,
            maxLength: 500,
          })}
        />
      </label>
      {formState.errors.note && (
        <p id={`note-error-${item.line}`} role="alert" className="-mt-2 text-[12.5px] text-err">
          {t("review.noteRequired")}
        </p>
      )}
      <label className="flex items-center gap-2 text-[13px]">
        <input
          type="checkbox"
          className="size-4 accent-[var(--color-ink)]"
          {...register("remember")}
        />
        {t("review.remember")}
      </label>
      {save.isError && (
        <p role="alert" className="text-[13px] text-err">
          {save.error.message}
        </p>
      )}
      <div>
        <Button variant="primary" type="submit" disabled={save.isPending}>
          {t("review.save")}
        </Button>
      </div>
    </form>
  );
}

function LineSheet({
  runId,
  item,
  findings,
  onClose,
}: {
  runId: string;
  item: BomItem | null;
  findings: Finding[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog.Root open={item != null} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/20" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-0 right-0 z-50 flex h-full w-[min(440px,100vw)] flex-col overflow-auto border-l border-line bg-surface shadow-[-12px_0_40px_rgba(21,24,30,0.12)]"
        >
          {item && (
            <>
              <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
                <div>
                  <Dialog.Title className="text-[16px] font-semibold">
                    {t("runPage.details", { line: item.line })}
                  </Dialog.Title>
                  <p className="text-[13px] text-muted">{item.refdes.join(", ")}</p>
                </div>
                <Dialog.Close
                  className="rounded-md p-1 text-muted hover:bg-paper"
                  aria-label={t("bom.close")}
                >
                  <svg viewBox="0 0 20 20" className="size-5" aria-hidden>
                    <path
                      d="M5 5l10 10M15 5L5 15"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                    />
                  </svg>
                </Dialog.Close>
              </div>
              <div className="px-5 py-4">
                <p className="font-[family-name:var(--font-mono)] text-[15px]">{item.mpn || "–"}</p>
                <p className="text-[13px] text-muted">{item.manufacturer}</p>
                <p className="mt-2 text-[13.5px]">{item.description}</p>
              </div>
              <section className="border-t border-line px-5 py-4">
                <h3 className="mb-2 text-[13.5px] font-semibold">{t("bom.findings")}</h3>
                {findings.length === 0 ? (
                  <p className="text-[13px] text-ok">{t("bom.noFindings")}</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {findings.map((f) => (
                      <li key={`${f.rule_id}-${f.message}`} className="text-[13px]">
                        <SeverityChip severity={f.severity} />{" "}
                        <span className="font-medium">{ruleTitle(f.rule_id) ?? f.message}</span>
                        {ruleTitle(f.rule_id) && (
                          <span className="block text-[12.5px] text-ink-soft">{f.message}</span>
                        )}
                        <span className="block text-[12px] text-muted">
                          {f.rule_id} · {f.rule_pack}@{f.rule_pack_version}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section className="border-t border-line px-5 py-4">
                <h3 className="mb-1 text-[13.5px] font-semibold">{t("runPage.fields")}</h3>
                <ul>
                  {Object.entries(item.provenance).map(([field, p]) => (
                    <ProvenanceDetail key={field} field={field} p={p} />
                  ))}
                </ul>
              </section>
              <section className="border-t border-line px-5 py-4">
                <h3 className="mb-2 text-[13.5px] font-semibold">{t("review.title")}</h3>
                <EditLine key={`${item.line}-${item.mpn}-${item.dnp}`} runId={runId} item={item} />
              </section>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function BomTable({ bom, runId }: { bom: BomVersion; runId: string }) {
  const { t } = useTranslation();
  const { notify } = useApp();
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const byLine = useMemo(() => findingsByLine(bom), [bom]);
  const general = bom.findings.filter((f) => f.line == null);
  const rows = bom.items.filter((i) => {
    if (!onlyIssues) return true;
    const w = worstSeverity(byLine.get(i.line));
    return w != null && w !== "info";
  });
  const selectedItem = bom.items.find((i) => i.line === selected) ?? null;

  function exportCsv() {
    const blob = new Blob([toCsv(bom)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${bom.design_name}-${bom.variant}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    notify(t("run.exported"));
  }

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[16px] font-semibold">
          BOM{" "}
          <span className="font-normal text-muted">
            · {t("run.lines", { count: bom.items.length })}
          </span>
        </h2>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-[13.5px]">
            <input
              type="checkbox"
              checked={onlyIssues}
              onChange={(e) => setOnlyIssues(e.target.checked)}
              className="size-4 accent-[var(--color-ink)]"
            />
            {t("run.onlyIssues")}
          </label>
          <Button onClick={exportCsv}>{t("run.export")}</Button>
        </div>
      </div>
      {general.length > 0 && (
        <Card className="mb-3 p-4">
          <h3 className="mb-2 text-[13.5px] font-semibold">{t("runPage.generalFindings")}</h3>
          <ul className="flex flex-col gap-1.5">
            {general.map((f) => (
              <li key={`${f.rule_id}-${f.message}`} className="text-[13px]">
                <SeverityChip severity={f.severity} />{" "}
                <span className="font-medium">{ruleTitle(f.rule_id) ?? f.message}</span>
                {ruleTitle(f.rule_id) && <span className="text-ink-soft"> – {f.message}</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <TableScroll label={"BOM"}>
        <table className="w-full min-w-[960px] text-left text-[13px]">
          <thead className="text-[12px] text-muted">
            <tr className="border-b border-line">
              <th scope="col" className="w-1 p-0">
                <span className="sr-only">{t("bom.source")}</span>
              </th>
              <th scope="col" className="px-3 py-2.5 font-medium">
                #
              </th>
              <th scope="col" className="px-3 py-2.5 font-medium">
                {t("bom.refdes")}
              </th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">
                {t("bom.qty")}
              </th>
              <th scope="col" className="px-3 py-2.5 font-medium">
                {t("bom.value")}
              </th>
              <th scope="col" className="px-3 py-2.5 font-medium">
                {t("bom.footprint")}
              </th>
              <th scope="col" className="px-3 py-2.5 font-medium">
                {t("bom.mpn")}
              </th>
              <th scope="col" className="px-3 py-2.5 font-medium whitespace-nowrap">
                {t("bom.who")}
              </th>
              <th scope="col" className="px-3 py-2.5 font-medium">
                {t("bom.check")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="px-5 py-6 text-muted">
                  {t("runPage.noIssues")}
                </td>
              </tr>
            )}
            {rows.map((i) => {
              const kind = lineProvenance(i);
              return (
                <tr
                  key={i.line}
                  className={clsx(
                    "border-b border-line last:border-b-0 hover:bg-paper",
                    i.dnp && "text-muted",
                  )}
                >
                  <td className="w-1 p-0" style={{ background: PROV_STRIPE[kind] }} aria-hidden />
                  <td className="px-3 py-2 text-muted">{i.line}</td>
                  <td className="max-w-[180px] px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setSelected(i.line)}
                      className="text-left font-medium underline-offset-2 hover:underline"
                    >
                      {i.refdes.join(", ")}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-right font-[family-name:var(--font-mono)]">
                    {i.quantity}
                  </td>
                  <td className="px-3 py-2">{i.value_normalized ?? i.value}</td>
                  <td className="max-w-[200px] truncate px-3 py-2 text-muted" title={i.footprint}>
                    {shortFootprint(i.footprint)}
                  </td>
                  <td className="px-3 py-2">
                    <Mono>{i.mpn || "–"}</Mono>
                    {i.manufacturer && (
                      <span className="block text-[12px] text-muted">{i.manufacturer}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <ProvChip kind={kind} />
                  </td>
                  <td className="px-3 py-2">
                    <SeverityChip severity={worstSeverity(byLine.get(i.line))} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>
      <LineSheet
        runId={runId}
        item={selectedItem}
        findings={selected != null ? (byLine.get(selected) ?? []) : []}
        onClose={() => setSelected(null)}
      />
    </section>
  );
}

export function RunPage() {
  const { t } = useTranslation();
  const { runId } = useParams({ from: "/shell/runs/$runId" });
  const { api, orgId } = useApp();
  const qc = useQueryClient();
  const run = useQuery({ queryKey: [orgId, "run", runId], queryFn: () => api.getRun(runId) });
  const done = run.data?.status === "completed" || run.data?.status === "failed";
  const trace = useQuery({
    queryKey: [orgId, "trace", runId],
    queryFn: () => api.getTrace(runId),
    enabled: run.isSuccess,
    retry: false,
  });
  const bom = useQuery({
    queryKey: [orgId, "bom", runId],
    queryFn: () => api.getBom(runId),
    enabled: run.data?.status === "completed",
  });

  // one live subscription per run until it finishes (not one per update)
  const live = run.isSuccess && !done;
  useEffect(() => {
    if (!live) return;
    return api.watchRun(runId, (updated) => {
      qc.setQueryData([orgId, "run", runId], updated);
      void qc.invalidateQueries({ queryKey: [orgId, "trace", runId] });
      if (updated.status === "completed" || updated.status === "failed") {
        void qc.invalidateQueries({ queryKey: [orgId, "runs"] });
      }
    });
  }, [api, runId, orgId, qc, live]);

  if (run.isError) return <EmptyState>{run.error.message}</EmptyState>;
  if (!run.data) return <Skeleton className="h-64" />;
  const r = run.data;

  return (
    <>
      <Link to="/runs" className="mb-3 inline-block text-[13px] text-muted hover:text-ink">
        ← {t("runPage.back")}
      </Link>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            <VariantBadge variant={r.variant} />
            {r.variant.startsWith("A") ? t("newRun.variantA") : t("newRun.variantB")}
          </span>
        }
        lead={
          <span className="flex flex-wrap items-center gap-2">
            <RunStatus status={r.status} />
            <span>{modelLabel(r.model_id)}</span>
            {r.review_edits > 0 && (
              <span className="rounded-[var(--radius-chip)] bg-user-bg px-2 py-px text-[11.5px] font-semibold text-user">
                {t("review.badge", { count: r.review_edits })}
              </span>
            )}
          </span>
        }
        actions={
          r.status === "completed" && (
            <Link
              to="/compare"
              search={{
                a: r.variant.startsWith("A") ? r.id : undefined,
                b: r.variant.startsWith("A") ? undefined : r.id,
              }}
              className="inline-flex h-9 items-center rounded-[var(--radius-control)] border border-line-strong bg-surface px-3.5 text-[13.5px] font-medium hover:bg-paper"
            >
              {t("runPage.compareWith")}
            </Link>
          )
        }
      />
      {isSimulatedModel(r.model_id) && (
        <p className="mb-5 rounded-[var(--radius-control)] border border-warn/30 bg-warn-bg px-4 py-2.5 text-[13px] text-warn">
          {t("compare.simulated")}
        </p>
      )}
      {r.status === "failed" && (
        <p
          role="alert"
          className="mb-5 rounded-[var(--radius-control)] bg-err-bg px-4 py-2.5 text-[13px] text-err"
        >
          {t("runPage.failed")}: {r.error}
        </p>
      )}
      <Card className="mb-6 p-5">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-4">
          <h2 className="text-[14px] font-semibold">{t("run.steps")}</h2>
          {done && trace.data && <UsageBar trace={trace.data} />}
        </div>
        <Steps trace={trace.data?.trace ?? []} running={!done} />
      </Card>
      {r.status === "completed" && bom.data ? (
        <BomTable bom={bom.data} runId={r.id} />
      ) : r.status === "failed" ? null : (
        <EmptyState>{t("run.waiting")}</EmptyState>
      )}
    </>
  );
}
