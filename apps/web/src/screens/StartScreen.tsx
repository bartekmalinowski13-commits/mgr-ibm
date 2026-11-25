import { Button, type Status, StatusBadge, TitleBlock, VariantChip } from "@bomagent/ui";
import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { Trans, useTranslation } from "react-i18next";
import { formatDuration } from "../lib/format";
import { SheetSlot, usePageTitle, useShell } from "../lib/layout";
import { formatEur } from "../lib/provenance";
import {
  useIsAdmin,
  useIsOwner,
  useMe,
  useModels,
  useProjects,
  useRuns,
  useUsage,
} from "../lib/queries";
import { useSession } from "../lib/session";
import { AddSamplesButton } from "./common";
import { FirstBomChecklist } from "./FirstBomChecklist";
import { TEMPLATES, TemplateArt } from "./templates";

const STATUS: Record<string, Status> = {
  queued: "pending",
  running: "running",
  completed: "ok",
  failed: "error",
  budget_exceeded: "warn",
};

const shortId = (id: string) => id.slice(0, 8);
const bold = { b: <strong className="font-semibold" /> };

/** Sheet 1 of the flow (ADR-0019): greeting, start from a device, recent runs. */
export function StartScreen() {
  const { t, i18n } = useTranslation();
  const { session, orgId } = useSession();
  const { openNewRun } = useShell();
  usePageTitle(t("nav.start"), { header: false });
  const projects = useProjects();
  const runs = useRuns();
  const me = useMe();
  const isOwner = useIsOwner();
  const isAdmin = useIsAdmin();
  const usage = useUsage(isAdmin);
  const models = useModels();
  const lang = i18n.language;

  const noSamples = !!projects.data && !projects.data.items.some((p) => p.is_sample);
  const items = runs.data?.items ?? [];
  const active = items.filter((r) => r.status === "queued" || r.status === "running");
  const done = items.filter((r) => r.status === "completed");
  const newestDone = done[0];
  const name = (session?.name || session?.email || "").split(" ")[0];
  const projectName = (id: string) => projects.data?.items.find((p) => p.id === id)?.name ?? "—";

  const orgName = me.data?.organizations.find((o) => o.org_id === orgId)?.name ?? "—";
  const limit = usage.data?.limits.llm_budget_eur_per_month;
  const cost = usage.data?.usage.cost_eur;
  const budget =
    limit && cost !== undefined
      ? t("start.budgetValue", {
          percent: Math.round((cost / limit) * 100),
          limit: formatEur(limit, lang),
        })
      : "—";
  const plan = usage.data ? t(`plan.names.${usage.data.plan}`) : "—";
  const modelsList = Array.isArray(models.data) ? models.data : [];

  return (
    <div className="flex flex-col gap-10">
      <SheetSlot name="titleBlock">
        <TitleBlock
          label={t("sheet.titleBlock")}
          name={orgName}
          sheetLabel={t("sheet.number", { n: 1, m: 4 })}
          cells={[
            { label: t("titleBlock.plan"), value: plan },
            { label: t("titleBlock.budget"), value: budget },
            { label: t("titleBlock.region"), value: "EU" },
            { label: t("titleBlock.defaultModel"), value: modelsList[0]?.id ?? "—" },
            {
              label: t("titleBlock.projects"),
              value: projects.data ? String(projects.data.items.length) : "—",
            },
            {
              label: t("titleBlock.members"),
              value:
                usage.data?.usage.members !== undefined ? String(usage.data.usage.members) : "—",
            },
          ]}
        />
      </SheetSlot>

      <header className="flex flex-col gap-4">
        <h2 className="font-display text-[44px] font-extrabold leading-[1.02] tracking-tight sm:text-[64px]">
          {t("start.greeting", { name })}
        </h2>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <p className="max-w-[60ch] text-[18px] leading-snug">
            {runs.data && items.length === 0 ? t("start.lead.empty") : null}
            {newestDone ? (
              <Trans
                i18nKey="start.lead.review"
                count={done.length}
                values={{ id: shortId(newestDone.id) }}
                components={bold}
              />
            ) : null}
            {newestDone && active.length > 0 ? " " : null}
            {active.length > 0 ? (
              <Trans
                i18nKey="start.lead.running"
                count={active.length}
                values={{ id: shortId(active[0]?.id ?? "") }}
                components={bold}
              />
            ) : null}
          </p>
          {newestDone ? (
            <Link
              to="/runs/$runId/bom"
              params={{ runId: newestDone.id }}
              className="inline-flex h-10 items-center rounded-control border border-ink px-4 font-medium hover:bg-vellum"
            >
              {t("start.reviewNotes")}
            </Link>
          ) : null}
        </div>
      </header>

      {projects.data && runs.data ? (
        <FirstBomChecklist
          counts={{
            projects: projects.data.items.filter((p) => !p.is_sample).length,
            runs: items.length,
            completed: done.length,
          }}
          onNewProject={() => undefined}
          onNewRun={() => openNewRun()}
        />
      ) : null}

      <section aria-labelledby="templates-title" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h3 id="templates-title" className="text-[22px] font-semibold">
            {t("start.templatesTitle")}
          </h3>
          <p className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[15px] text-muted">
            {isOwner && noSamples ? <AddSamplesButton /> : null}
            <Link
              to="/projects"
              className="inline-flex min-h-10 items-center underline underline-offset-4 hover:text-ink"
            >
              {t("start.templatesHint")}
            </Link>
          </p>
        </div>
        <ul className="grid grid-cols-2 border-b border-r border-ink sm:grid-cols-3 lg:grid-cols-5">
          <li className="border-l border-t border-ink">
            <button
              type="button"
              onClick={() => openNewRun()}
              className="hatch flex h-full min-h-[200px] w-full flex-col items-center justify-center gap-3 p-4 text-center focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ink"
            >
              <span className="grid size-12 place-items-center rounded-full border border-ink bg-sheet">
                <Plus size={20} aria-hidden />
              </span>
              <span className="font-semibold">{t("start.blank")}</span>
            </button>
          </li>
          {(Object.keys(TEMPLATES) as (keyof typeof TEMPLATES)[]).map((key) => (
            <li
              key={key}
              className="border-l border-t border-ink last:col-span-2 sm:last:col-span-2 lg:last:col-span-1"
            >
              <button
                type="button"
                onClick={() => openNewRun({ template: key })}
                className="flex h-full w-full flex-col items-start gap-3 p-4 text-left hover:bg-vellum focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ink"
              >
                <span className="flex w-full justify-center pt-4 pb-2">
                  <TemplateArt template={key} />
                </span>
                <span>
                  <span className="block text-[17px] font-semibold leading-snug">
                    {t(`start.templates.${key}.title`)}
                  </span>
                  <span className="block text-[15px] text-muted">
                    {t(`start.templates.${key}.hint`)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="recent-title" className="flex flex-col gap-3">
        <h3 id="recent-title" className="text-[22px] font-semibold">
          {t("start.recent.title")}
        </h3>
        {runs.data && items.length === 0 ? (
          <p className="text-[16px]">
            {t("start.recent.empty")}{" "}
            <Button variant="secondary" onClick={() => openNewRun()}>
              {t("start.recent.emptyAction")}
            </Button>
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-left">
              <thead>
                <tr className="border-b border-ink text-[14px] font-normal text-muted">
                  <th scope="col" className="px-3 py-2 font-normal">
                    {t("start.recent.number")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-normal">
                    {t("start.recent.project")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-normal">
                    {t("start.recent.variant")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-normal">
                    {t("start.recent.state")}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-normal">
                    {t("start.recent.cost")}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-normal">
                    {t("start.recent.time")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.slice(0, 5).map((r) => {
                  const label = t(`run.status.${r.status}`, { defaultValue: r.status });
                  const cost = Number(r.usage.cost_eur ?? 0);
                  const seconds = Number(r.usage.wall_time_s ?? 0);
                  const state = r.status === "failed" && r.error ? `${label}: ${r.error}` : label;
                  return (
                    <tr key={r.id} className="border-b border-line-soft">
                      <td className="px-3 py-3 font-data">
                        {r.status === "completed" ? (
                          <Link
                            to="/runs/$runId/bom"
                            params={{ runId: r.id }}
                            className="underline-offset-4 hover:underline"
                          >
                            #{shortId(r.id)}
                          </Link>
                        ) : (
                          <Link
                            to="/runs/$runId"
                            params={{ runId: r.id }}
                            className="underline-offset-4 hover:underline"
                          >
                            #{shortId(r.id)}
                          </Link>
                        )}
                      </td>
                      <td className="px-3 py-3 font-semibold">{projectName(r.project_id)}</td>
                      <td className="px-3 py-3">
                        <VariantChip
                          variant={r.variant === "A" ? "A" : "B"}
                          label={t(`variants.${r.variant}`, { defaultValue: r.variant })}
                        />
                      </td>
                      <td className="px-3 py-3">
                        <StatusBadge status={STATUS[r.status] ?? "pending"} label={state} />
                      </td>
                      <td className="px-3 py-3 text-right font-data">{formatEur(cost, lang)}</td>
                      <td className="px-3 py-3 text-right font-data">{formatDuration(seconds)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
