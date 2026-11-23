import { Button, EmptyState } from "@bomagent/ui";
import { useTranslation } from "react-i18next";
import { usePageTitle, useShell } from "../lib/layout";
import { useProjects, useRuns } from "../lib/queries";
import { LoadError, RunTable, Skeleton } from "./common";

export function RunsScreen() {
  const { t } = useTranslation();
  usePageTitle(t("runs.title"));
  const { openNewRun } = useShell();
  const runs = useRuns();
  const projects = useProjects();
  const names = new Map((projects.data?.items ?? []).map((p) => [p.id, p.name]));
  if (runs.isPending) return <Skeleton />;
  if (runs.isError) return <LoadError error={runs.error} onRetry={() => void runs.refetch()} />;
  if (!runs.data.items.length)
    return (
      <EmptyState
        title={t("empty.runs.title")}
        body={t("empty.runs.body")}
        action={<Button onClick={() => openNewRun()}>{t("empty.runs.action")}</Button>}
      />
    );
  return <RunTable runs={runs.data.items} projects={names} />;
}
