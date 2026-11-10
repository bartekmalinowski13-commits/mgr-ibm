import { Button, Select } from "@bomagent/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage } from "../lib/api";
import { formatDate } from "../lib/format";
import { usePageTitle } from "../lib/layout";
import { useSession } from "../lib/session";
import { LoadError, Skeleton } from "./common";

const OBJECT_TYPES = [
  "organization",
  "project",
  "file",
  "run",
  "bom",
  "member",
  "invitation",
  "api_key",
];

export function AuditScreen() {
  const { t, i18n } = useTranslation();
  usePageTitle(t("audit.title"));
  const { orgId } = useSession();
  const [objectType, setObjectType] = useState("");
  const [verdict, setVerdict] = useState<{ ok: boolean; text: string }>();
  const events = useInfiniteQuery({
    queryKey: ["audit", orgId, objectType],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      call(
        api.GET("/v1/audit-events", {
          params: {
            query: {
              limit: 50,
              ...(objectType ? { object_type: objectType } : {}),
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const verify = async () => {
    try {
      const r = await call(api.GET("/v1/audit-events/verify"));
      setVerdict(
        r.ok
          ? { ok: true, text: t("audit.verifyOk", { count: r.checked }) }
          : { ok: false, text: t("audit.verifyBroken", { seq: r.first_broken_seq }) },
      );
    } catch (err) {
      setVerdict({ ok: false, text: problemMessage(err) });
    }
  };
  const rows = events.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1.5 font-medium">
          {t("audit.objectType")}
          <Select
            value={objectType}
            onChange={(e) => setObjectType(e.target.value)}
            className="w-56"
          >
            <option value="">{t("audit.all")}</option>
            {OBJECT_TYPES.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </Select>
        </label>
        <Button variant="secondary" className="ml-auto" onClick={() => void verify()}>
          <ShieldCheck size={16} aria-hidden /> {t("audit.verify")}
        </Button>
      </div>
      {verdict ? (
        <p
          role="status"
          className={`rounded-card border p-3 ${verdict.ok ? "border-ok/30 bg-ok/5" : "border-error/30 bg-error/5"}`}
        >
          {verdict.text}
        </p>
      ) : null}
      {events.isPending ? (
        <Skeleton rows={5} />
      ) : events.isError ? (
        <LoadError error={events.error} onRetry={() => void events.refetch()} />
      ) : rows.length === 0 ? (
        <p className="text-muted">{t("audit.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-card border border-line bg-surface">
          <table className="w-full min-w-[720px] text-left text-[14px]">
            <thead className="border-b border-line text-[13px] text-muted">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  #
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("audit.when")}
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("audit.action")}
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("audit.objectType")}
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("audit.actor")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.seq} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 tabular-nums text-muted">{e.seq}</td>
                  <td className="px-4 py-2.5">{formatDate(e.occurred_at, i18n.language)}</td>
                  <td className="px-4 py-2.5 font-mono text-[13px]">{e.action}</td>
                  <td className="px-4 py-2.5">
                    {e.object_type}{" "}
                    <span className="font-mono text-[12px] text-muted">
                      {e.object_id.slice(0, 8)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    {e.actor_id} <span className="text-muted">({e.actor_type})</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {events.hasNextPage ? (
        <Button
          variant="secondary"
          className="self-start"
          onClick={() => void events.fetchNextPage()}
        >
          {t("audit.more")}
        </Button>
      ) : null}
    </div>
  );
}
