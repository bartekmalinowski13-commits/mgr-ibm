import { TitleBlock } from "@bomagent/ui";
import { useTranslation } from "react-i18next";
import type { Schemas } from "../lib/api";
import { useProjects, useRuns, useRuntime } from "../lib/queries";

/** Revision letter from the BOM version: 1 = A, 2 = B, ... (digits past Z). */
export function revisionLetter(version: number): string {
  return version >= 1 && version <= 26 ? String.fromCharCode(64 + version) : String(version);
}

/**
 * The drawing title block of a run: project, BOM revision, run number, date, variant, sheet.
 * Real data; on a demo deployment the status cell reads "Illustrative".
 */
export function RunTitleBlock({
  run,
  version,
  variantLabel,
  className,
}: {
  run: Schemas["Run"];
  version: number;
  /** override the variant cell (comparison: "A and B") */
  variantLabel?: string;
  className?: string;
}) {
  const { t, i18n } = useTranslation();
  const demo = useRuntime().data?.mode === "demo";
  const projects = useProjects();
  const runs = useRuns(run.project_id);
  const project = projects.data?.items.find((p) => p.id === run.project_id);
  // the run's ordinal within its project (oldest first), else the short id
  const ordered = [...(runs.data?.items ?? [])].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );
  const idx = ordered.findIndex((r) => r.id === run.id);
  const date = new Intl.DateTimeFormat(i18n.language, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(run.created_at));
  return (
    <TitleBlock
      className={className}
      label={t("titleBlock.label")}
      title={project?.name ?? t("run.title")}
      revision={t("titleBlock.revision", { rev: revisionLetter(version) })}
      run={t("titleBlock.run", { id: idx >= 0 ? idx + 1 : run.id.slice(0, 8) })}
      date={date}
      status={t(`run.status.${run.status}`, run.status)}
      demo={demo ? t("titleBlock.illustrative") : undefined}
      variant={variantLabel ?? t("run.variant", { variant: run.variant })}
      sheet={t("titleBlock.sheetOf", { n: 1, total: 1 })}
      sheetLabel={t("titleBlock.sheet")}
    />
  );
}
