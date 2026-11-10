import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { useRef } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { kbMimeType } from "../api/client";
import type { KbDocument, KbKind } from "../api/types";
import { Button, Card, EmptyState, PageHeader, Skeleton, TableScroll } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { useApp } from "../state";

const KINDS: KbKind[] = ["datasheet", "application_note", "standard", "component_library", "other"];

const STATUS_TONE: Record<KbDocument["status"], string> = {
  pending: "bg-parser-bg text-parser",
  indexing: "bg-llm-bg text-llm",
  indexed: "bg-ok-bg text-ok",
  failed: "bg-err-bg text-err",
};

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} kB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const inputCls =
  "h-9 w-full rounded-[var(--radius-control)] border border-line bg-paper px-3 text-[13.5px] focus:border-ink focus:bg-surface focus:outline-none";

interface UploadForm {
  title: string;
  kind: KbKind;
  manufacturer: string;
}

function UploadCard() {
  const { t } = useTranslation();
  const { api, orgId, notify } = useApp();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const { register, getValues, trigger, reset, formState } = useForm<UploadForm>({
    defaultValues: { title: "", kind: "datasheet", manufacturer: "" },
  });
  const upload = useMutation({
    mutationFn: (file: File) => {
      if (!kbMimeType(file.name)) throw new Error(t("kb.unsupported"));
      const v = getValues();
      return api.uploadKbDocument(file, {
        title: v.title.trim() || file.name.replace(/\.[^.]+$/, ""),
        kind: v.kind,
        manufacturer: v.manufacturer.trim(),
      });
    },
    onSuccess: async () => {
      reset();
      notify(t("kb.added"));
      await qc.invalidateQueries({ queryKey: [orgId, "kb"] });
    },
  });

  return (
    <Card className="mb-6 p-5">
      <h2 className="font-semibold">{t("kb.upload")}</h2>
      <p className="mt-0.5 max-w-[80ch] text-[13px] text-muted">{t("kb.uploadHint")}</p>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-[2fr_1fr_1fr_auto] md:items-end">
        <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
          {t("kb.titleField")}
          <input className={inputCls} {...register("title", { maxLength: 500 })} />
        </label>
        <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
          {t("kb.kind")}
          <select className={inputCls} {...register("kind")}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`kb.kinds.${k}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
          {t("kb.manufacturer")}
          <input className={inputCls} {...register("manufacturer", { maxLength: 200 })} />
        </label>
        <Button
          variant="primary"
          disabled={upload.isPending || formState.isSubmitting}
          onClick={async () => {
            if (await trigger()) input.current?.click();
          }}
        >
          {upload.isPending ? t("kb.uploading") : t("kb.choose")}
        </Button>
      </div>
      <input
        ref={input}
        type="file"
        className="sr-only"
        aria-label={t("kb.upload")}
        data-testid="kb-file"
        accept=".pdf,.md,.txt,.html"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) upload.mutate(file);
          e.target.value = "";
        }}
      />
      {upload.isError && (
        <p role="alert" className="mt-2 text-[13px] text-err">
          {upload.error.message}
        </p>
      )}
    </Card>
  );
}

export function KnowledgePage() {
  const { t } = useTranslation();
  const { api, orgId } = useApp();
  const docs = useQuery({
    queryKey: [orgId, "kb"],
    queryFn: () => api.listKbDocuments(),
    refetchInterval: (q) =>
      q.state.data?.items.some((d) => d.status === "pending" || d.status === "indexing")
        ? 700
        : false,
  });

  return (
    <>
      <PageHeader title={t("kb.title")} lead={t("kb.lead")} />
      <UploadCard />
      {docs.isPending ? (
        <Skeleton className="h-48" />
      ) : docs.isError ? (
        <EmptyState>{docs.error.message}</EmptyState>
      ) : !docs.data.items.length ? (
        <EmptyState>{t("kb.empty")}</EmptyState>
      ) : (
        <TableScroll label={t("kb.title")}>
          <table className="w-full min-w-[760px] text-left text-[13.5px]">
            <thead className="text-[12.5px] text-muted">
              <tr className="border-b border-line">
                <th scope="col" className="px-5 py-2.5 font-medium">
                  {t("kb.titleField")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("kb.kind")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("kb.manufacturer")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  Status
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  {t("kb.size")}
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t("kb.added_at")}
                </th>
              </tr>
            </thead>
            <tbody>
              {docs.data.items.map((d) => (
                <tr key={d.id} className="border-b border-line last:border-b-0">
                  <td className="px-5 py-2.5">
                    <span className="font-medium">{d.title}</span>
                    <span
                      className={clsx(
                        "ml-2 rounded-[var(--radius-chip)] px-2 py-px text-[11.5px] font-semibold",
                        d.scope === "global"
                          ? "bg-review-bg text-review"
                          : "bg-paper text-ink-soft",
                      )}
                    >
                      {t(`kb.scope.${d.scope}`)}
                    </span>
                    {d.error && <span className="block text-[12.5px] text-err">{d.error}</span>}
                  </td>
                  <td className="px-3 py-2.5 text-muted">
                    {t(`kb.kinds.${d.kind}`, { defaultValue: d.kind })}
                  </td>
                  <td className="px-3 py-2.5 text-muted">{d.manufacturer || "–"}</td>
                  <td className="px-3 py-2.5">
                    <span
                      className={clsx(
                        "rounded-[var(--radius-chip)] px-2 py-px text-[11.5px] font-semibold",
                        STATUS_TONE[d.status],
                      )}
                    >
                      {t(`kb.status.${d.status}`)}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-[family-name:var(--font-mono)] text-[12.5px]">
                    {formatSize(d.size_bytes)}
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap text-muted">
                    {formatDateTime(d.created_at)}
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
