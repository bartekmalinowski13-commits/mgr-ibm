import * as RadioGroup from "@radix-ui/react-radio-group";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { VariantBadge } from "../components/RunStatus";
import { Card, EmptyState, Mono, PageHeader, Skeleton, TableScroll } from "../components/ui";
import i18n from "../i18n";
import { formatDateTime } from "../lib/format";
import { useApp } from "../state";

export function AuditPage() {
  const { t } = useTranslation();
  const { api, orgId } = useApp();
  const audit = useQuery({ queryKey: [orgId, "audit"], queryFn: () => api.auditEvents() });
  return (
    <>
      <PageHeader title={t("audit.title")} lead={t("audit.lead")} />
      {audit.isPending ? (
        <Skeleton className="h-64" />
      ) : audit.isError ? (
        <EmptyState>{audit.error.message}</EmptyState>
      ) : (
        <TableScroll label={t("audit.title")}>
          <table className="w-full min-w-[760px] text-left text-[13px]">
            <thead className="text-[12px] text-muted">
              <tr className="border-b border-line">
                <th scope="col" className="px-5 py-2.5 font-medium">
                  #
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("audit.when")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("audit.who")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("audit.what")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("audit.object")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  SHA-256
                </th>
              </tr>
            </thead>
            <tbody>
              {audit.data.items.map((e) => (
                <tr key={e.seq} className="border-b border-line last:border-b-0">
                  <td className="px-5 py-2 text-muted">{e.seq}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{formatDateTime(e.occurred_at)}</td>
                  <td className="px-3 py-2">
                    {e.actor_id}
                    {e.actor_type === "service" && (
                      <span className="ml-1 text-[12px] text-muted">(usługa)</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Mono>{e.action}</Mono>
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {e.object_type} <Mono>{e.object_id?.slice(0, 8)}</Mono>
                  </td>
                  <td className="px-3 py-2 text-muted">
                    <Mono>{e.hash.slice(0, 12)}…</Mono>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </>
  );
}

export function NotificationsPage() {
  const { t } = useTranslation();
  const { api, orgId } = useApp();
  const runs = useQuery({ queryKey: [orgId, "runs"], queryFn: () => api.listRuns() });
  const items = (runs.data?.items ?? []).filter(
    (r) => r.status === "completed" || r.status === "failed",
  );
  return (
    <>
      <PageHeader title={t("notifications.title")} lead={t("notifications.lead")} />
      {runs.isPending ? (
        <Skeleton className="h-40" />
      ) : items.length === 0 ? (
        <EmptyState>{t("notifications.empty")}</EmptyState>
      ) : (
        <Card>
          <ul>
            {items.map((r) => (
              <li key={r.id} className="border-t border-line first:border-t-0">
                <Link
                  to="/runs/$runId"
                  params={{ runId: r.id }}
                  className="flex items-center gap-3 px-5 py-3 hover:bg-paper"
                >
                  <VariantBadge variant={r.variant} />
                  <span className={r.status === "failed" ? "text-err" : undefined}>
                    {r.status === "failed"
                      ? t("notifications.runFailed", { variant: r.variant })
                      : t("notifications.runDone", { variant: r.variant })}
                  </span>
                  <span className="ml-auto text-[12.5px] text-muted">
                    {formatDateTime(r.finished_at ?? r.created_at)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const sections = ["members", "sso", "apiKeys", "limits"] as const;
  return (
    <>
      <PageHeader title={t("settings.title")} />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="font-semibold">{t("settings.language")}</h2>
          <RadioGroup.Root
            className="mt-3 flex gap-2"
            aria-label={t("settings.language")}
            value={i18n.language}
            onValueChange={(lng) => {
              localStorage.setItem("bomagent_lang", lng);
              void i18n.changeLanguage(lng);
            }}
          >
            {(["pl", "en"] as const).map((lng) => (
              <RadioGroup.Item
                key={lng}
                value={lng}
                className="h-9 rounded-[var(--radius-control)] border border-line-strong px-3.5 text-[13.5px] data-[state=checked]:border-ink data-[state=checked]:bg-ink data-[state=checked]:text-white"
              >
                {lng === "pl" ? "Polski" : "English"}
              </RadioGroup.Item>
            ))}
          </RadioGroup.Root>
        </Card>
        {sections.map((s) => (
          <Card key={s} className="p-5">
            <h2 className="font-semibold">{t(`settings.${s}`)}</h2>
            <p className="mt-1 text-[13px] text-muted">{t("settings.soon")}</p>
          </Card>
        ))}
      </div>
    </>
  );
}
