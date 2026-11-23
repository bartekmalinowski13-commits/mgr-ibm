import { Link } from "@tanstack/react-router";
import { Check, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { firstBomSteps, type StepKey } from "../lib/checklist";

const KEY = "bomagent.checklist.dismissed";

function wasDismissed(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

/** "First BOM in 3 steps" card: hidden once complete or dismissed. */
export function FirstBomChecklist({
  counts,
  onNewProject,
  onNewRun,
}: {
  counts: { projects: number; runs: number; completed: number };
  onNewProject: () => void;
  onNewRun: () => void;
}) {
  const { t } = useTranslation();
  const [dismissed, setDismissed] = useState(wasDismissed);
  const { steps, next, complete } = firstBomSteps(counts);
  if (dismissed || complete) return null;
  const done = steps.filter((s) => s.done).length;
  const action = (key: StepKey) => {
    const cls = "font-medium underline underline-offset-4 focus-visible:outline-2";
    const label = t(`checklist.steps.${key}.action`);
    if (key === "project")
      return (
        <Link to="/projects" onClick={onNewProject} className={cls}>
          {label}
        </Link>
      );
    if (key === "run")
      return (
        <button type="button" onClick={onNewRun} className={cls}>
          {label}
        </button>
      );
    return (
      <Link to="/runs" className={cls}>
        {label}
      </Link>
    );
  };
  return (
    <section
      aria-labelledby="checklist-title"
      data-testid="first-bom-checklist"
      className=" border border-ink bg-sheet p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 id="checklist-title" className="font-display text-2xl font-semibold">
            {t("checklist.title")}
          </h3>
          <p className="mt-1 text-ink-soft">{t("checklist.progress", { done })}</p>
        </div>
        <button
          type="button"
          aria-label={t("checklist.dismiss")}
          onClick={() => {
            setDismissed(true);
            try {
              localStorage.setItem(KEY, "1");
            } catch {
              /* private mode: the card just returns next visit */
            }
          }}
          className=" p-1.5 text-ink-soft hover:bg-tint hover:text-ink"
        >
          <X size={18} aria-hidden />
        </button>
      </div>
      <ol className="mt-4 grid gap-3 md:grid-cols-3">
        {steps.map((s, i) => (
          <li
            key={s.key}
            aria-current={s.key === next ? "step" : undefined}
            className={`flex gap-3 border p-4 ${s.key === next ? "border-ink" : "border-rule"}`}
          >
            <span
              aria-hidden
              className={`grid size-7 shrink-0 place-items-center text-sm font-semibold ${
                s.done ? "bg-ink text-sheet" : "border border-ink text-ink-soft"
              }`}
            >
              {s.done ? <Check size={16} /> : i + 1}
            </span>
            <div className="flex flex-col gap-1">
              <p className="font-medium">{t(`checklist.steps.${s.key}.title`)}</p>
              <p className="text-sm text-ink-soft">{t(`checklist.steps.${s.key}.hint`)}</p>
              {s.done ? <span className="sr-only">{t("checklist.done")}</span> : null}
              {s.key === next ? <p className="text-[15px]">{action(s.key)}</p> : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
