import { Button, StatusBadge } from "@bomagent/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { UploadCloud } from "lucide-react";
import { type DragEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage, uploadFile } from "../lib/api";
import { formatBytes } from "../lib/format";
import { usePageTitle, useShell } from "../lib/layout";
import { useRuns } from "../lib/queries";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { projectRoute } from "../router";
import { LoadError, RunTable, Skeleton } from "./common";

const FILE_STATUS = { uploaded: "running", parsed: "ok", failed: "error" } as const;

export function ProjectScreen() {
  const { projectId } = projectRoute.useParams();
  const { t, i18n } = useTranslation();
  const { orgId } = useSession();
  const { openNewRun } = useShell();
  const toast = useToast();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const project = useQuery({
    queryKey: ["project", orgId, projectId],
    queryFn: () =>
      call(api.GET("/v1/projects/{project_id}", { params: { path: { project_id: projectId } } })),
  });
  const files = useQuery({
    queryKey: ["files", orgId, projectId],
    queryFn: () =>
      call(
        api.GET("/v1/projects/{project_id}/files", { params: { path: { project_id: projectId } } }),
      ),
    refetchInterval: (q) => (q.state.data?.some((f) => f.status === "uploaded") ? 1500 : false),
  });
  const runs = useRuns(projectId);
  usePageTitle(project.data?.name ?? t("projects.title"));

  const upload = async (list: FileList | null) => {
    if (!list?.length) return;
    setBusy(true);
    try {
      for (const file of Array.from(list)) await uploadFile(projectId, file);
      toast(t("projects.uploaded", { count: list.length }));
    } catch (err) {
      toast(problemMessage(err), "error");
    } finally {
      setBusy(false);
      await queryClient.invalidateQueries({ queryKey: ["files", orgId, projectId] });
    }
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    void upload(e.dataTransfer.files);
  };

  if (project.isError) return <LoadError error={project.error} />;
  const ready = files.data?.some((f) => f.status === "parsed");
  const finished = new Set(
    (runs.data?.items ?? []).filter((r) => r.status === "completed").map((r) => r.variant),
  );
  const comparable = finished.has("A") && finished.has("B");

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="files-title" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="files-title" className="font-display text-2xl font-bold">
            {t("projects.files")}
          </h2>
          <Button onClick={() => openNewRun({ projectId })} disabled={!ready}>
            {t("projects.startRun")}
          </Button>
        </div>
        {/* biome-ignore lint/a11y/noStaticElementInteractions: drop target only; the "choose from disk" button is the keyboard path */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center gap-2 rounded-card border-2 border-dashed p-8 text-center ${
            dragging ? "border-llm bg-llm/5" : "border-line bg-surface"
          }`}
        >
          <UploadCloud size={28} aria-hidden className="text-muted" />
          <p>
            {t("projects.drop")}{" "}
            <button
              type="button"
              disabled={busy}
              onClick={() => input.current?.click()}
              className="font-medium underline underline-offset-4"
            >
              {t("projects.browse")}
            </button>
          </p>
          <p className="text-sm text-muted">{t("projects.dropHint")}</p>
          <input
            ref={input}
            type="file"
            multiple
            className="sr-only"
            aria-label={t("projects.browse")}
            onChange={(e) => void upload(e.target.files)}
            data-testid="file-input"
          />
        </div>
        {files.isPending ? (
          <Skeleton rows={2} />
        ) : files.data?.length ? (
          <ul className="divide-y divide-line rounded-card border border-line bg-surface">
            {files.data.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
                <span className="min-w-0 flex-1 truncate font-mono text-sm">{f.name}</span>
                <span className="text-sm text-muted">
                  {f.detected_format ?? ""}
                  {typeof f.summary.components === "number"
                    ? ` – ${t("projects.components", { count: f.summary.components as number })}`
                    : ""}
                </span>
                <span className="text-sm text-muted">
                  {formatBytes(f.size_bytes, i18n.language)}
                </span>
                <StatusBadge
                  status={FILE_STATUS[f.status as keyof typeof FILE_STATUS] ?? "pending"}
                  label={t(`projects.fileStatus.${f.status}`)}
                />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">{t("projects.noFiles")}</p>
        )}
      </section>

      <section aria-labelledby="runs-title" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="runs-title" className="font-display text-2xl font-bold">
            {t("projects.runs")}
          </h2>
          {comparable ? (
            <Link
              to="/projects/$projectId/compare"
              params={{ projectId }}
              search={{}}
              className="font-medium underline underline-offset-4"
            >
              {t("compare.open")}
            </Link>
          ) : null}
        </div>
        {runs.data?.items.length ? (
          <RunTable runs={runs.data.items} />
        ) : (
          <p className="text-muted">{t("projects.noRuns")}</p>
        )}
      </section>
    </div>
  );
}
