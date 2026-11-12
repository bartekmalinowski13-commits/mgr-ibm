import { Link } from "@tanstack/react-router";
import { Plus, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { usePageTitle, useShell } from "../lib/layout";
import { useIsOwner, useProjects, useRuns } from "../lib/queries";
import { useSession } from "../lib/session";
import { AddSamplesButton } from "./common";
import { TEMPLATES, TemplateArt } from "./templates";

export function StartScreen() {
  const { t } = useTranslation();
  const { session } = useSession();
  const { openNewRun } = useShell();
  usePageTitle(t("nav.start"));
  const projects = useProjects();
  const runs = useRuns();
  const isOwner = useIsOwner();
  const noSamples = !!projects.data && !projects.data.items.some((p) => p.is_sample);
  const [panelOpen, setPanelOpen] = useState(true);
  const items = runs.data?.items ?? [];
  const active = items.filter((r) => r.status === "queued" || r.status === "running");
  const done = items.filter((r) => r.status === "completed");

  const stats = [
    {
      label: t("start.stats.activeRuns"),
      value: active.length,
      empty: t("start.stats.activeRunsEmpty"),
      action: () => openNewRun(),
      actionLabel: t("nav.newRun"),
      to: "/runs" as const,
    },
    {
      label: t("start.stats.projects"),
      value: projects.data?.items.length ?? 0,
      empty: t("start.stats.projectsEmpty"),
      to: "/projects" as const,
      actionLabel: t("projects.new"),
    },
    {
      label: t("start.stats.completed"),
      value: done.length,
      empty: t("start.stats.completedEmpty"),
      to: "/runs" as const,
    },
  ];

  return (
    <div className="flex flex-col gap-10">
      <h2 className="font-display text-[44px] font-extrabold leading-[1.02] tracking-tight sm:text-[64px]">
        {t("start.greeting", { name: session?.name || session?.email })}
      </h2>

      {panelOpen ? (
        <section
          aria-labelledby="new-run-title"
          className="rounded-panel border border-line bg-surface p-6"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 id="new-run-title" className="font-display text-2xl font-bold">
                {t("start.newRunTitle")}
              </h3>
              <p className="mt-1 max-w-[70ch] text-muted">{t("start.newRunLead")}</p>
            </div>
            <button
              type="button"
              aria-label={t("common.close")}
              onClick={() => setPanelOpen(false)}
              className="rounded-control p-1.5 text-muted hover:bg-paper hover:text-ink"
            >
              <X size={18} aria-hidden />
            </button>
          </div>
          <ul className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <li>
              <button
                type="button"
                onClick={() => openNewRun()}
                className="flex h-full w-full flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-line p-6 text-center hover:border-ink/40 focus-visible:outline-2 focus-visible:outline-focus"
              >
                <span className="grid size-10 place-items-center rounded-full bg-ink text-surface">
                  <Plus size={20} aria-hidden />
                </span>
                <span className="font-medium">{t("start.blank")}</span>
                <span className="text-sm text-muted">{t("start.blankHint")}</span>
              </button>
            </li>
            {(Object.keys(TEMPLATES) as (keyof typeof TEMPLATES)[]).map((key) => (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => openNewRun({ template: key })}
                  className="w-full overflow-hidden rounded-card border border-line text-left hover:border-ink/40 focus-visible:outline-2 focus-visible:outline-focus"
                >
                  <span className="block bg-paper/60">
                    <TemplateArt template={key} />
                  </span>
                  <span className="block p-3">
                    <span className="block font-medium">{t(`start.templates.${key}.title`)}</span>
                    <span className="block text-sm text-muted">
                      {t(`start.templates.${key}.hint`)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="grid gap-4 md:grid-cols-3">
        {stats.map((s) => (
          <div
            key={s.label}
            className="flex flex-col gap-2 rounded-card border border-line bg-surface p-5"
          >
            <h3 className="text-muted">{s.label}</h3>
            {s.value > 0 ? (
              <Link to={s.to} className="font-display text-4xl font-extrabold hover:underline">
                {s.value}
              </Link>
            ) : (
              <p className="text-[15px]">
                {s.empty}{" "}
                {s.action ? (
                  <button
                    type="button"
                    onClick={s.action}
                    className="font-medium underline underline-offset-4"
                  >
                    {s.actionLabel}
                  </button>
                ) : s.actionLabel ? (
                  <Link to={s.to} className="font-medium underline underline-offset-4">
                    {s.actionLabel}
                  </Link>
                ) : null}
              </p>
            )}
            {s.to === "/projects" && isOwner && noSamples ? <AddSamplesButton /> : null}
          </div>
        ))}
      </section>
    </div>
  );
}
