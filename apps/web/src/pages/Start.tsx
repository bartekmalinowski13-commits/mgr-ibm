import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Run } from "../api/types";
import {
  BlankCover,
  EcgCover,
  EegCover,
  GuideArt,
  InfusionCover,
  Spo2Cover,
} from "../components/Illustrations";
import { Card, Skeleton } from "../components/ui";
import { worstSeverity } from "../lib/bom";
import { useApp } from "../state";

const TEMPLATES = [
  { key: "ecg", Cover: EcgCover },
  { key: "eeg", Cover: EegCover },
  { key: "spo2", Cover: Spo2Cover },
  { key: "infusion", Cover: InfusionCover },
] as const;

function useOverview() {
  const { api, orgId } = useApp();
  const runs = useQuery({ queryKey: [orgId, "runs"], queryFn: () => api.listRuns() });
  const projects = useQuery({ queryKey: [orgId, "projects"], queryFn: () => api.listProjects() });
  const completed = (runs.data?.items ?? []).filter((r) => r.status === "completed");
  // lines to review: findings that need an engineer, from the two most recent finished runs
  const latest = completed.slice(0, 2);
  const review = useQuery({
    queryKey: [orgId, "to-review", latest.map((r) => r.id)],
    queryFn: async () => {
      const boms = await Promise.all(latest.map((r) => api.getBom(r.id)));
      return boms.reduce(
        (n, b) =>
          n +
          b.items.filter((i) => {
            const worst = worstSeverity(b.findings.filter((f) => f.line === i.line));
            return worst === "error" || worst === "warning" || worst === "review";
          }).length,
        0,
      );
    },
    enabled: runs.isSuccess,
  });
  const active = (runs.data?.items ?? []).filter(
    (r: Run) => r.status === "queued" || r.status === "running",
  );
  return {
    loading: runs.isPending || projects.isPending,
    active: active.length,
    completed: completed.length,
    projects: projects.data?.items.length ?? 0,
    toReview: review.data ?? 0,
  };
}

function Stat({ to, label, tone }: { to: "/runs" | "/projects"; label: string; tone: string }) {
  return (
    <Link
      to={to}
      className="group flex items-center gap-3 rounded-[var(--radius-card)] border border-line bg-surface px-4 py-3.5 hover:border-line-strong"
    >
      <span className="size-2.5 shrink-0 rounded-full" style={{ background: tone }} aria-hidden />
      <span className="text-[14px] font-medium">{label}</span>
    </Link>
  );
}

export function StartPage() {
  const { t } = useTranslation();
  const { api, orgId, userName, openNewRun, notify } = useApp();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [panelOpen, setPanelOpen] = useState(true);
  const o = useOverview();

  async function fromTemplate(name: string) {
    const p = await api.createProject(name);
    await qc.invalidateQueries({ queryKey: [orgId] });
    notify(t("project.created"));
    await navigate({ to: "/projects/$projectId", params: { projectId: p.id } });
  }

  return (
    <div className="flex flex-col gap-8">
      <h1 className="greeting font-[family-name:var(--font-display)] text-[40px] leading-[1.05] font-bold tracking-[-0.02em] sm:text-[48px]">
        {t("start.hello", { name: userName })}
      </h1>

      {panelOpen && (
        <Card className="relative p-5 sm:p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-[16px] font-semibold">{t("start.newRunTitle")}</h2>
            <button
              type="button"
              onClick={() => setPanelOpen(false)}
              className="rounded-md p-1 text-muted hover:bg-paper"
              aria-label={t("start.close")}
            >
              <svg viewBox="0 0 20 20" className="size-5" aria-hidden>
                <path
                  d="M5 5l10 10M15 5L5 15"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
          <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
            <li>
              <Link to="/projects" className="group block">
                <div className="aspect-[5/3] overflow-hidden rounded-[10px] border border-dashed border-line-strong">
                  <BlankCover title={t("start.blank")} />
                </div>
                <p className="mt-2 text-[13.5px] font-medium group-hover:underline">
                  {t("start.blank")}
                </p>
                <p className="text-[12.5px] text-muted">{t("start.blankHint")}</p>
              </Link>
            </li>
            {TEMPLATES.map(({ key, Cover }) => {
              const title = t(`start.templates.${key}`);
              return (
                <li key={key}>
                  <button
                    type="button"
                    onClick={() => fromTemplate(title)}
                    className="group block w-full text-left"
                  >
                    <div className="aspect-[5/3] overflow-hidden rounded-[10px]">
                      <Cover title={title} />
                    </div>
                    <p className="mt-2 text-[13.5px] font-medium group-hover:underline">{title}</p>
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      <section
        aria-label={t("nav.runs")}
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4"
      >
        {o.loading ? (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[52px]" />)
        ) : (
          <>
            <Stat
              to="/runs"
              tone="var(--color-llm)"
              label={t("start.stats.activeRuns", { count: o.active })}
            />
            <Stat
              to="/runs"
              tone="var(--color-review)"
              label={t("start.stats.toReview", { count: o.toReview })}
            />
            <Stat
              to="/projects"
              tone="var(--color-rule)"
              label={t("start.stats.projects", { count: o.projects })}
            />
            <Stat
              to="/runs"
              tone="var(--color-parser)"
              label={t("start.stats.completed", { count: o.completed })}
            />
          </>
        )}
      </section>

      <section>
        <div className="mb-3 flex items-end justify-between gap-4">
          <div>
            <h2 className="text-[16px] font-semibold">{t("start.guides")}</h2>
            <p className="text-muted">{t("start.guidesLead")}</p>
          </div>
          <button
            type="button"
            onClick={() => openNewRun()}
            className="text-[13.5px] font-medium text-llm underline-offset-2 hover:underline"
          >
            {t("nav.newRun")}
          </button>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {([1, 2, 3] as const).map((n) => (
            <Card key={n} className="overflow-hidden">
              <div className="aspect-[16/7]">
                <GuideArt variant={n} />
              </div>
              <div className="p-4">
                <h3 className="font-semibold">{t(`start.guide${n}`)}</h3>
                <p className="mt-1 text-[13px] text-muted">{t(`guides.g${n}`)}</p>
              </div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
