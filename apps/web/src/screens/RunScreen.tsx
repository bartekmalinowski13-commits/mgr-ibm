import {
  Button,
  buttonClass,
  cn,
  ProvenanceGlyph,
  TitleBlock,
  VariantChip,
  ViaTimeline,
  type ViaTrack,
} from "@bomagent/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage, type RunProgress, type Schemas, streamRun } from "../lib/api";
import { formatDate, formatDuration, formatNumber } from "../lib/format";
import { useIntentKeys } from "../lib/idempotency";
import { SheetSlot, usePageTitle } from "../lib/layout";
import { formatEur } from "../lib/provenance";
import { useProjects, useRuns } from "../lib/queries";
import { useSession } from "../lib/session";
import {
  currentStage,
  executorKey,
  type Stage,
  type StageState,
  stageStates,
  stageTime,
  type TraceStep,
} from "../lib/stages";
import { useToast } from "../lib/toast";
import { runRoute } from "../router";
import { LoadError, RunStatus, Skeleton } from "./common";

const TERMINAL = new Set(["completed", "failed", "budget_exceeded"]);
/** The API marks a cancelled run as failed with this error text. */
const CANCELLED = "cancelled by user";
/** Runs of "both and compare" are created one after the other for the same project. */
const SIBLING_WINDOW_MS = 120_000;

type Run = Schemas["Run"];

/** Live state of one run: SSE progress while it runs, the step trace (polled while running). */
function useLiveRun(run: Run | undefined) {
  const { orgId } = useSession();
  const queryClient = useQueryClient();
  const [live, setLive] = useState<RunProgress>();
  const [seen, setSeen] = useState<{ step: string; at: number }[]>([]);
  const id = run?.id;
  const terminal = !run || TERMINAL.has(run.status);
  useEffect(() => {
    if (!id || terminal) return;
    const ctrl = new AbortController();
    void streamRun(
      id,
      (p) => {
        setLive(p);
        if (p.step)
          setSeen((prev) =>
            prev.some((e) => e.step === p.step)
              ? prev
              : [...prev, { step: p.step as string, at: Date.now() }],
          );
      },
      ctrl.signal,
    )
      .then(() => queryClient.invalidateQueries({ queryKey: ["run", orgId, id] }))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [id, terminal, orgId, queryClient]);
  const status = live?.status ?? run?.status;
  const trace = useQuery({
    queryKey: ["trace", orgId, id],
    queryFn: () =>
      call(api.GET("/v1/runs/{run_id}/trace", { params: { path: { run_id: id ?? "" } } })),
    enabled: !!id,
    refetchInterval: status === "running" ? 3000 : false,
  });
  return { status, live, seen, trace: (trace.data ?? []) as TraceStep[] };
}

export function RunScreen() {
  const { runId } = runRoute.useParams();
  const { t, i18n } = useTranslation();
  const { orgId } = useSession();
  const toast = useToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const keys = useIntentKeys();
  const [rerunning, setRerunning] = useState(false);
  const run = useQuery({
    queryKey: ["run", orgId, runId],
    queryFn: () => call(api.GET("/v1/runs/{run_id}", { params: { path: { run_id: runId } } })),
  });
  const projects = useProjects();
  const projectRuns = useRuns(run.data?.project_id);
  const project = projects.data?.items.find((p) => p.id === run.data?.project_id);
  // the other variant started together with this run ("both and compare")
  const sibling = useMemo(() => {
    const me = run.data;
    if (!me) return undefined;
    const at = Date.parse(me.created_at);
    return (projectRuns.data?.items ?? [])
      .filter((r) => r.id !== me.id && r.variant !== me.variant)
      .find((r) => Math.abs(Date.parse(r.created_at) - at) < SIBLING_WINDOW_MS);
  }, [run.data, projectRuns.data]);
  const main = useLiveRun(run.data);
  const other = useLiveRun(sibling);
  const short = runId.slice(0, 8);
  usePageTitle(t("run.heading", { id: short }));

  const lang = i18n.language;
  if (run.isPending) return <Skeleton rows={4} />;
  if (run.isError) return <LoadError error={run.error} onRetry={() => void run.refetch()} />;

  const pairs = [
    { run: run.data, live: main },
    ...(sibling ? [{ run: sibling, live: other }] : []),
  ].sort((a, b) => a.run.variant.localeCompare(b.run.variant));
  const status = main.status ?? run.data.status;
  const finished = TERMINAL.has(status);
  const cancelled = status === "failed" && run.data.error === CANCELLED;

  const states = new Map(
    pairs.map((p) => [
      p.run.id,
      stageStates(p.live.status ?? p.run.status, p.live.trace, p.live.live?.step),
    ]),
  );

  const cancel = async () => {
    if (!window.confirm(t("run.confirmCancel"))) return;
    try {
      await call(api.POST("/v1/runs/{run_id}/cancel", { params: { path: { run_id: runId } } }));
      await queryClient.invalidateQueries({ queryKey: ["run", orgId, runId] });
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      toast(t("run.cancelled"));
    } catch (err) {
      toast(problemMessage(err), "error");
    }
  };

  const rerun = async () => {
    if (rerunning) return;
    setRerunning(true);
    try {
      const next = await call(
        api.POST("/v1/runs/{run_id}/rerun", {
          params: { path: { run_id: runId } },
          // a retry after an error replays the same rerun instead of starting another one
          headers: { "Idempotency-Key": keys.keyFor(`rerun:${runId}`, runId) },
        }),
      );
      keys.done(`rerun:${runId}`);
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      toast(t("run.rerunStarted"));
      await navigate({ to: "/runs/$runId", params: { runId: next.id } });
    } catch (err) {
      toast(problemMessage(err), "error");
    } finally {
      setRerunning(false);
    }
  };

  const tracks: ViaTrack[] = pairs.map(({ run: r }) => ({
    label: t(`variants.${r.variant}`, { defaultValue: r.variant }),
    tone: r.variant === "A" ? "llm" : "rule",
    steps: (states.get(r.id) ?? []).map((s) => ({
      name: t(`run.stages.${s.stage}`),
      state: s.state,
      time: stageTime(s, t("run.via.running")),
      executor: t(`run.executors.${executorKey(r.variant, s)}`),
    })),
  }));

  const bothDone =
    pairs.length === 2 && pairs.every((p) => (p.live.status ?? p.run.status) === "completed");
  const runA = pairs.find((p) => p.run.variant === "A")?.run;
  const runB = pairs.find((p) => p.run.variant === "B")?.run;

  return (
    <>
      <SheetSlot name="crumbs">
        <Link to="/runs" className="hover:text-ink hover:underline">
          {t("nav.runs")}
        </Link>
        <span aria-hidden>/</span>
        {project ? (
          <>
            <Link
              to="/projects/$projectId"
              params={{ projectId: project.id }}
              className="hover:text-ink hover:underline"
            >
              {project.name}
            </Link>
            <span aria-hidden>/</span>
          </>
        ) : null}
      </SheetSlot>
      <SheetSlot name="chips">
        {pairs.map((p) => (
          <VariantChip
            key={p.run.id}
            variant={p.run.variant}
            label={t(`variants.${p.run.variant}`, { defaultValue: p.run.variant })}
          />
        ))}
        <RunStatus status={status} />
      </SheetSlot>
      <SheetSlot name="actions">
        {status === "queued" || status === "running" ? (
          <Button variant="secondary" onClick={() => void cancel()}>
            {t("run.stop")}
          </Button>
        ) : null}
        {finished ? (
          <Button variant="secondary" disabled={rerunning} onClick={() => void rerun()}>
            {t("run.rerun")}
          </Button>
        ) : null}
        {bothDone && runA && runB ? (
          <Link
            to="/projects/$projectId/compare"
            params={{ projectId: run.data.project_id }}
            search={{ a: runA.id, b: runB.id }}
            className={buttonClass("secondary")}
          >
            {t("compare.open")}
          </Link>
        ) : null}
        {status === "completed" || status === "budget_exceeded" ? (
          <Link to="/runs/$runId/bom" params={{ runId }} className={buttonClass("primary")}>
            {t("run.openBom")}
          </Link>
        ) : null}
      </SheetSlot>
      <SheetSlot name="titleBlock">
        <TitleBlock
          label={t("sheet.titleBlock")}
          name={t("run.blockName", { id: short })}
          sheetLabel={t("sheet.number", { n: 2, m: 4 })}
          cells={[
            { label: t("titleBlock.project"), value: project?.name ?? "—" },
            { label: t("titleBlock.variant"), value: pairs.map((p) => p.run.variant).join(" + ") },
            { label: t("titleBlock.model"), value: run.data.model_id },
            { label: t("titleBlock.runtime"), value: run.data.runtime },
            {
              label: t("titleBlock.kb"),
              value: run.data.kb_snapshot_id ? run.data.kb_snapshot_id.slice(0, 16) : "—",
            },
            {
              label: t("titleBlock.start"),
              value: formatDate(run.data.started_at ?? run.data.created_at, lang),
            },
          ]}
        />
      </SheetSlot>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-10 xl:grid-cols-[minmax(0,1fr)_minmax(280px,30%)]">
        <div className="flex min-w-0 flex-col gap-10">
          <div>
            <h2 className="max-w-[22ch] font-display text-[34px] sm:text-[44px]">
              {headline(
                t,
                pairs.map((p) => ({
                  variant: p.run.variant,
                  status: p.live.status ?? p.run.status,
                  error: p.run.error,
                  states: states.get(p.run.id) ?? [],
                })),
              )}
            </h2>
            <p className="mt-4 max-w-[62ch] text-[17px] text-muted">
              {pairs.length === 2
                ? t("run.leadBoth")
                : t("run.leadOne", { model: run.data.model_id })}
            </p>
            {status === "queued" ? <p className="mt-2 text-muted">{t("run.waiting")}</p> : null}
            {cancelled ? (
              <p role="status" className="mt-2 text-muted">
                {t("run.cancelledHelp")}
              </p>
            ) : status === "failed" ? (
              <p role="alert" className="mt-2 text-error">
                {t("run.failedHelp", { error: run.data.error ?? "" })}
              </p>
            ) : null}
          </div>

          <section aria-labelledby="timeline-title">
            <h2 id="timeline-title" className="sr-only">
              {t("run.timeline")}
            </h2>
            <ViaTimeline
              label={t("run.timeline")}
              tracks={tracks}
              stateLabels={{
                done: t("run.via.done"),
                current: t("run.via.current"),
                todo: t("run.via.todo"),
              }}
            />
            <p aria-live="polite" className="sr-only">
              {pairs
                .map((p) => {
                  const now = currentStage(states.get(p.run.id) ?? []);
                  return now ? `${p.run.variant}: ${t(`run.stages.${now}`)}` : "";
                })
                .filter(Boolean)
                .join("; ")}
            </p>
          </section>

          <Counters
            rows={pairs.map((p) => ({
              variant: p.run.variant,
              usage:
                (TERMINAL.has(p.live.status ?? p.run.status) ? p.run.usage : p.live.live?.usage) ??
                p.run.usage ??
                {},
            }))}
          />
        </div>

        <Events
          pairs={pairs.map((p) => ({
            run: p.run,
            trace: p.live.trace,
            seen: p.live.seen,
            status: p.live.status ?? p.run.status,
          }))}
        />
      </div>
    </>
  );
}

type TFn = ReturnType<typeof useTranslation>["t"];

/** The sheet title is a conclusion about where the run(s) are, never a section name. */
function headline(
  t: TFn,
  runs: { variant: string; status: string; error: string | null; states: StageState[] }[],
): string {
  const phrase = (s: Stage | undefined, status: string) =>
    status === "completed"
      ? t("run.phrase.done")
      : status === "queued"
        ? t("run.phrase.queued")
        : status === "running" && s
          ? t(`run.phrase.${s}`)
          : t(`run.phrase.${status === "failed" ? "failed" : "stopped"}`);
  if (runs.length === 1) {
    const [r] = runs;
    if (!r) return "";
    if (r.status === "failed" && r.error === CANCELLED) return t("run.headline.cancelled");
    if (r.status === "completed") return t("run.headline.completed");
    if (r.status === "failed") return t("run.headline.failed");
    if (r.status === "budget_exceeded") return t("run.headline.budget");
    if (r.status === "queued") return t("run.headline.queued");
    return t("run.headline.one", {
      variant: r.variant,
      phrase: phrase(currentStage(r.states), r.status),
    });
  }
  const rank = (r: (typeof runs)[number]) =>
    r.status === "completed" ? 10 : r.states.filter((s) => s.state === "done").length;
  const [lead, lag] = [...runs].sort((a, b) => rank(b) - rank(a)) as [
    (typeof runs)[number],
    (typeof runs)[number],
  ];
  const leadPhrase = phrase(currentStage(lead.states), lead.status);
  const lagPhrase = phrase(currentStage(lag.states), lag.status);
  if (lead.status === "completed" && lag.status === "completed") return t("run.headline.bothDone");
  if (rank(lead) === rank(lag) && leadPhrase === lagPhrase)
    return t("run.headline.same", { a: runs[0]?.variant, b: runs[1]?.variant, phrase: leadPhrase });
  return t("run.headline.lead", { lead: lead.variant, leadPhrase, lag: lag.variant, lagPhrase });
}

function Counters({ rows }: { rows: { variant: string; usage: Record<string, unknown> }[] }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const n = (u: Record<string, unknown>, k: string) => Number(u[k] ?? 0);
  return (
    <section aria-labelledby="counters-title">
      <h2 id="counters-title" className="sr-only">
        {t("run.counters")}
      </h2>
      <section
        aria-label={t("run.counters")}
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be reachable by keyboard
        tabIndex={0}
        className="relative overflow-x-auto"
      >
        <table className="w-full min-w-[620px] border-collapse text-left">
          <tbody>
            {rows.map((r) => {
              const cells = [
                { label: t("run.time"), value: formatDuration(n(r.usage, "wall_time_s")) },
                {
                  label: t("run.tokens"),
                  value: formatNumber(
                    n(r.usage, "input_tokens") + n(r.usage, "output_tokens"),
                    lang,
                  ),
                },
                { label: t("run.llmCalls"), value: formatNumber(n(r.usage, "llm_calls"), lang) },
                { label: t("run.cost"), value: formatEur(n(r.usage, "cost_eur"), lang) },
              ];
              return (
                <tr key={r.variant} className="border-t border-line-soft">
                  <th
                    scope="row"
                    className={cn(
                      "w-[22%] py-4 pr-4 text-[17px] font-semibold",
                      r.variant === "A" ? "text-llm" : r.variant === "B" ? "text-rule" : "",
                    )}
                  >
                    <span className="inline-flex items-center gap-2">
                      <ProvenanceGlyph kind={r.variant === "A" ? "agent" : "rule"} />
                      {t("run.variant", { variant: r.variant })}
                    </span>
                  </th>
                  {cells.map((c) => (
                    <td key={c.label} className="border-l border-line-soft px-4 py-3">
                      <span className="block text-[14px] text-muted">{c.label}</span>
                      <span className="block font-data text-[17px]">{c.value}</span>
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </section>
  );
}

interface EventRow {
  key: string;
  at: number;
  variant: string;
  text: string;
}

/** Finished steps, newest first: from the trace (start time + durations) and from live SSE. */
function Events({
  pairs,
}: {
  pairs: { run: Run; trace: TraceStep[]; seen: { step: string; at: number }[]; status: string }[];
}) {
  const { t, i18n } = useTranslation();
  const time = new Intl.DateTimeFormat(i18n.language, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const rows: EventRow[] = [];
  for (const { run, trace, seen, status } of pairs) {
    let clock = Date.parse(run.started_at ?? run.created_at);
    const nodes = new Set<string>();
    trace.forEach((s, i) => {
      clock += s.duration_s * 1000;
      nodes.add(s.node);
      rows.push({
        key: `${run.id}-${i}`,
        at: clock,
        variant: run.variant,
        text: t(`run.events.${s.node}`, {
          defaultValue: t("run.events.other", { node: s.node }),
          count: s.llm_calls,
          variant: run.variant,
          context: run.variant === "A" ? "a" : undefined,
        }),
      });
    });
    for (const e of seen)
      if (!nodes.has(e.step))
        rows.push({
          key: `${run.id}-live-${e.step}`,
          at: e.at,
          variant: run.variant,
          text: t(`run.events.${e.step}`, {
            defaultValue: t("run.events.other", { node: e.step }),
            count: 0,
            context: run.variant === "A" ? "a" : undefined,
          }),
        });
    if (TERMINAL.has(status) && run.finished_at)
      rows.push({
        key: `${run.id}-end`,
        at: Date.parse(run.finished_at),
        variant: run.variant,
        text: t("run.events.end", {
          variant: run.variant,
          status: t(`run.status.${status}`, status),
        }),
      });
  }
  rows.sort((a, b) => b.at - a.at);
  return (
    <section
      aria-labelledby="events-title"
      className="xl:-my-8 xl:border-l xl:border-line-soft xl:py-8 xl:pl-8"
    >
      <h2 id="events-title" className="text-[19px] font-semibold">
        {t("run.eventsTitle")}
      </h2>
      {rows.length ? (
        <ol className="mt-4 flex flex-col">
          {rows.map((r) => (
            <li
              key={r.key}
              className="grid grid-cols-[auto_auto_1fr] gap-x-3 border-b border-line-soft py-3 text-[15px]"
            >
              <span className="font-data text-[12.5px] leading-6 text-muted">
                {time.format(r.at)}
              </span>
              <ProvenanceGlyph
                kind={r.variant === "A" ? "agent" : "rule"}
                label={t("run.variant", { variant: r.variant })}
                className="mt-[7px]"
              />
              <span>{r.text}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-muted">{t("run.eventsEmpty")}</p>
      )}
    </section>
  );
}
