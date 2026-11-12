import { Button, Input, Select, StatusBadge } from "@bomagent/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage, uploadKbDocument } from "../lib/api";
import { formatBytes, formatDate } from "../lib/format";
import { usePageTitle } from "../lib/layout";
import { useMe } from "../lib/queries";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { LoadError, Skeleton } from "./common";

const KINDS = ["datasheet", "application_note", "standard", "component_library", "other"] as const;
const STATUS = { pending: "pending", indexing: "running", indexed: "ok", failed: "error" } as const;
type Scope = "tenant" | "global";

export function KbScreen() {
  const { t, i18n } = useTranslation();
  usePageTitle(t("kb.title"));
  const { orgId } = useSession();
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [scope, setScope] = useState<Scope>("tenant");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("datasheet");
  const [manufacturer, setManufacturer] = useState("");
  const [busy, setBusy] = useState(false);
  const roles = me.data?.organizations.find((o) => o.org_id === orgId)?.roles ?? [];
  const canWrite = roles.some((r) => r === "owner" || r === "admin" || r === "engineer");
  const docs = useQuery({
    queryKey: ["kb", orgId, scope],
    queryFn: () => call(api.GET("/v1/kb/documents", { params: { query: { scope, limit: 100 } } })),
    refetchInterval: (q) =>
      q.state.data?.items.some((d) => d.status === "pending" || d.status === "indexing")
        ? 2000
        : false,
  });

  const upload = async (e: FormEvent) => {
    e.preventDefault();
    const file = input.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      await uploadKbDocument(file, kind, manufacturer);
      toast(t("kb.added", { name: file.name }));
      if (input.current) input.current.value = "";
      setManufacturer("");
      await qc.invalidateQueries({ queryKey: ["kb", orgId] });
    } catch (err) {
      toast(problemMessage(err), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <p className="max-w-[75ch] text-muted">{t("kb.lead")}</p>
      <div role="tablist" aria-label={t("kb.title")} className="flex gap-1 border-b border-line">
        {(["tenant", "global"] as const).map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={scope === id}
            onClick={() => setScope(id)}
            className={`-mb-px border-b-2 px-3 py-2 font-medium focus-visible:outline-2 focus-visible:outline-focus ${
              scope === id ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {t(`kb.tabs.${id}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="flex flex-col gap-4">
        {scope === "tenant" && canWrite ? (
          <form
            onSubmit={upload}
            className="grid gap-3 rounded-card border border-line bg-surface p-4 md:grid-cols-[1fr_200px_200px_auto] md:items-end"
          >
            <label className="flex flex-col gap-1.5 font-medium">
              {t("kb.file")}
              <input
                ref={input}
                type="file"
                required
                accept=".pdf,.md,.txt"
                className="rounded-control border border-line px-3 py-2 text-[15px] file:mr-3 file:rounded-control file:border-0 file:bg-paper file:px-3 file:py-1"
              />
            </label>
            <label className="flex flex-col gap-1.5 font-medium">
              {t("kb.kind")}
              <Select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`kb.kinds.${k}`)}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1.5 font-medium">
              {t("bom.columns.manufacturer")}
              <Input
                maxLength={120}
                value={manufacturer}
                onChange={(e) => setManufacturer(e.target.value)}
              />
            </label>
            <Button type="submit" disabled={busy}>
              {t("kb.add")}
            </Button>
            <p className="text-sm text-muted md:col-span-4">{t("kb.hint")}</p>
          </form>
        ) : null}
        {scope === "global" ? <p className="text-sm text-muted">{t("kb.globalLead")}</p> : null}
        {docs.isPending ? (
          <Skeleton />
        ) : docs.isError ? (
          <LoadError error={docs.error} onRetry={() => void docs.refetch()} />
        ) : docs.data.items.length === 0 ? (
          <p className="text-muted">{scope === "tenant" ? t("kb.empty") : t("kb.globalEmpty")}</p>
        ) : (
          <ul className="divide-y divide-line rounded-card border border-line bg-surface">
            {docs.data.items.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{d.title}</p>
                  <p className="text-sm text-muted">
                    {t(`kb.kinds.${d.kind}`, d.kind)}
                    {d.manufacturer ? ` – ${d.manufacturer}` : ""} –{" "}
                    {formatBytes(d.size_bytes, i18n.language)} –{" "}
                    {formatDate(d.created_at, i18n.language)}
                  </p>
                  {d.status === "failed" && d.error ? (
                    <p className="text-sm text-error">{d.error}</p>
                  ) : null}
                </div>
                {d.status === "indexed" ? (
                  <span className="text-sm text-muted">{t("kb.chunks", { count: d.chunks })}</span>
                ) : null}
                <StatusBadge status={STATUS[d.status]} label={t(`kb.status.${d.status}`)} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
