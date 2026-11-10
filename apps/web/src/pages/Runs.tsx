import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { RunStatus, VariantBadge } from "../components/RunStatus";
import { Button, EmptyState, PageHeader, Skeleton, TableScroll } from "../components/ui";
import { formatDateTime, modelLabel } from "../lib/format";
import { useApp } from "../state";

export function RunsPage() {
  const { t } = useTranslation();
  const { api, orgId, openNewRun } = useApp();
  const runs = useQuery({
    queryKey: [orgId, "runs"],
    queryFn: () => api.listRuns(),
    refetchInterval: (q) =>
      q.state.data?.items.some((r) => r.status === "queued" || r.status === "running")
        ? 1000
        : false,
  });

  return (
    <>
      <PageHeader
        title={t("runs.title")}
        lead={t("runs.lead")}
        actions={
          <Button variant="primary" onClick={() => openNewRun()}>
            {t("nav.newRun")}
          </Button>
        }
      />
      {runs.isPending ? (
        <Skeleton className="h-48" />
      ) : !runs.data?.items.length ? (
        <EmptyState>{t("empty.runs")}</EmptyState>
      ) : (
        <TableScroll label={t("runs.title")}>
          <table className="w-full text-left text-[13.5px]">
            <thead className="text-[12.5px] text-muted">
              <tr className="border-b border-line">
                <th scope="col" className="px-5 py-2.5 font-medium">
                  {t("runs.variant")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("runs.status")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("runs.model")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("runs.created")}
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.data.items.map((r) => (
                <tr key={r.id} className="border-b border-line last:border-b-0 hover:bg-paper">
                  <td className="px-5 py-2.5">
                    <Link
                      to="/runs/$runId"
                      params={{ runId: r.id }}
                      className="inline-flex items-center gap-2 font-medium underline-offset-2 hover:underline"
                      aria-label={t("runs.open", { variant: r.variant })}
                    >
                      <VariantBadge variant={r.variant} />
                      {r.variant.startsWith("A") ? t("newRun.variantA") : t("newRun.variantB")}
                    </Link>
                  </td>
                  <td className="px-3 py-2.5">
                    <RunStatus status={r.status} />
                  </td>
                  <td className="px-3 py-2.5 text-muted">{modelLabel(r.model_id)}</td>
                  <td className="px-3 py-2.5 text-muted">{formatDateTime(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </>
  );
}
