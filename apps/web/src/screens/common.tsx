import { type Status, StatusBadge } from "@bomagent/ui";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import type { Schemas } from "../lib/api";
import { problemMessage } from "../lib/api";
import { formatDate } from "../lib/format";

const RUN_STATUS: Record<string, Status> = {
  queued: "pending",
  running: "running",
  completed: "ok",
  failed: "error",
  budget_exceeded: "warn",
};

export function RunStatus({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <StatusBadge
      status={RUN_STATUS[status] ?? "pending"}
      label={t(`run.status.${status}`, status)}
    />
  );
}

export function RunTable({
  runs,
  projects,
}: {
  runs: Schemas["Run"][];
  projects?: Map<string, string>;
}) {
  const { t, i18n } = useTranslation();
  return (
    <div className="overflow-x-auto rounded-card border border-line bg-surface">
      <table className="w-full min-w-[640px] text-left">
        <thead className="border-b border-line text-sm text-muted">
          <tr>
            <th className="px-4 py-2.5 font-medium">{t("run.title")}</th>
            {projects ? <th className="px-4 py-2.5 font-medium">{t("newRun.project")}</th> : null}
            <th className="px-4 py-2.5 font-medium">{t("newRun.model")}</th>
            <th className="px-4 py-2.5 font-medium">{t("audit.when")}</th>
            <th className="px-4 py-2.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="border-b border-line last:border-0 hover:bg-paper/50">
              <td className="px-4 py-3">
                <Link
                  to="/runs/$runId"
                  params={{ runId: r.id }}
                  className="font-medium underline-offset-4 hover:underline"
                >
                  {t("run.variant", { variant: r.variant })}
                </Link>
              </td>
              {projects ? <td className="px-4 py-3">{projects.get(r.project_id) ?? "–"}</td> : null}
              <td className="px-4 py-3 font-mono text-sm">{r.model_id}</td>
              <td className="px-4 py-3 text-muted">{formatDate(r.created_at, i18n.language)}</td>
              <td className="px-4 py-3">
                <RunStatus status={r.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LoadError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div role="alert" className="rounded-card border border-error/30 bg-error/5 p-4">
      <p>{problemMessage(error) || t("common.unknownError")}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 font-medium underline underline-offset-4"
        >
          {t("common.retry")}
        </button>
      ) : null}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={t("common.loading")}
      className="flex flex-col gap-2"
    >
      {Array.from({ length: rows }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: placeholders
        <div key={i} className="h-12 rounded-card bg-line/50 motion-safe:animate-pulse" />
      ))}
    </div>
  );
}
