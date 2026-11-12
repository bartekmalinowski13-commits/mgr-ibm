import { useTranslation } from "react-i18next";
import { usePageTitle } from "../lib/layout";
import { useProjects, useRuns } from "../lib/queries";
import { LoadError, RunTable, Skeleton } from "./common";

export function RunsScreen() {
  const { t } = useTranslation();
  usePageTitle(t("runs.title"));
  const runs = useRuns();
  const projects = useProjects();
  const names = new Map((projects.data?.items ?? []).map((p) => [p.id, p.name]));
  if (runs.isPending) return <Skeleton />;
  if (runs.isError) return <LoadError error={runs.error} onRetry={() => void runs.refetch()} />;
  if (!runs.data.items.length) return <p className="text-muted">{t("runs.empty")}</p>;
  return <RunTable runs={runs.data.items} projects={names} />;
}
