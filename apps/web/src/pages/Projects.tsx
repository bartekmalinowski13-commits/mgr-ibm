import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { clsx } from "clsx";
import { useRef } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import type { Design } from "../api/types";
import { RunStatus, VariantBadge } from "../components/RunStatus";
import { Button, Card, EmptyState, Mono, PageHeader, Skeleton } from "../components/ui";
import { formatDateTime, modelLabel } from "../lib/format";
import { useApp } from "../state";

export function ProjectsPage() {
  const { t } = useTranslation();
  const { api, orgId, notify } = useApp();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data, isPending } = useQuery({
    queryKey: [orgId, "projects"],
    queryFn: () => api.listProjects(),
  });
  const { register, handleSubmit, reset, formState } = useForm<{ name: string }>();
  const create = handleSubmit(async ({ name }) => {
    const p = await api.createProject(name.trim());
    reset();
    await qc.invalidateQueries({ queryKey: [orgId] });
    notify(t("project.created"));
    await navigate({ to: "/projects/$projectId", params: { projectId: p.id } });
  });

  return (
    <>
      <PageHeader title={t("projects.title")} />
      <form onSubmit={create} className="mb-6 flex max-w-xl gap-2" noValidate>
        <label htmlFor="project-name" className="sr-only">
          {t("projects.namePlaceholder")}
        </label>
        <input
          id="project-name"
          placeholder={t("projects.namePlaceholder")}
          aria-invalid={formState.errors.name ? true : undefined}
          className="h-9 flex-1 rounded-[var(--radius-control)] border border-line bg-surface px-3 text-[13.5px] focus:border-ink focus:outline-none"
          {...register("name", {
            required: true,
            validate: (v) => v.trim().length > 0,
            maxLength: 200,
          })}
        />
        <Button variant="primary" type="submit" disabled={formState.isSubmitting}>
          {t("projects.create")}
        </Button>
      </form>
      {isPending ? (
        <Skeleton className="h-40" />
      ) : !data?.items.length ? (
        <EmptyState>{t("projects.empty")}</EmptyState>
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.items.map((p) => (
            <li key={p.id}>
              <Link
                to="/projects/$projectId"
                params={{ projectId: p.id }}
                className="block rounded-[var(--radius-card)] border border-line bg-surface p-4 hover:border-line-strong"
              >
                <p className="font-semibold">{p.name}</p>
                <p className="mt-1 text-[12.5px] text-muted">{formatDateTime(p.created_at)}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

const DESIGN_TONE: Record<string, string> = {
  parsed: "bg-ok-bg text-ok",
  failed: "bg-err-bg text-err",
  uploaded: "bg-llm-bg text-llm",
  awaiting_upload: "bg-parser-bg text-parser",
};

function DesignRow({ design }: { design: Design }) {
  const { t } = useTranslation();
  const { openNewRun } = useApp();
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 border-t border-line px-5 py-4 first:border-t-0">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={clsx(
              "rounded-[var(--radius-chip)] px-2 py-px text-[11.5px] font-semibold",
              DESIGN_TONE[design.status],
            )}
          >
            {t(`projects.status.${design.status}`, { defaultValue: design.status })}
          </span>
          {design.source_format && <Mono>{design.source_format}</Mono>}
          {design.components != null && (
            <span className="text-[12.5px] text-muted">
              {t("projects.components", { count: design.components })}
            </span>
          )}
        </div>
        <p className="mt-1.5 truncate text-[13.5px]">{design.filenames.join(", ")}</p>
        {design.error && (
          <p role="alert" className="mt-1 max-w-[70ch] text-[13px] text-err">
            {design.error}
          </p>
        )}
        {(design.limitations ?? []).map((l) => (
          <p key={l} className="mt-1 text-[12.5px] text-warn">
            {l}
          </p>
        ))}
      </div>
      <Button
        variant="primary"
        disabled={design.status !== "parsed"}
        onClick={() => openNewRun(design.id)}
      >
        {t("projects.runIt")}
      </Button>
    </li>
  );
}

export function ProjectDetailPage() {
  const { t } = useTranslation();
  const { projectId } = useParams({ from: "/shell/projects/$projectId" });
  const { api, orgId, notify } = useApp();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const project = useQuery({
    queryKey: [orgId, "projects"],
    queryFn: () => api.listProjects(),
    select: (page) => page.items.find((p) => p.id === projectId),
  });
  const designs = useQuery({
    queryKey: [orgId, "designs", projectId],
    queryFn: () => api.listDesigns(projectId),
    refetchInterval: (q) =>
      q.state.data?.items.some((d) => d.status === "uploaded") ? 500 : false,
  });
  const runs = useQuery({ queryKey: [orgId, "runs"], queryFn: () => api.listRuns() });
  const designIds = new Set((designs.data?.items ?? []).map((d) => d.id));
  const projectRuns = (runs.data?.items ?? []).filter((r) => designIds.has(r.design_id));
  const upload = useMutation({
    mutationFn: (files: File[]) => api.createDesign(projectId, files),
    onSuccess: async () => {
      notify(t("project.uploaded"));
      await qc.invalidateQueries({ queryKey: [orgId] });
    },
  });

  return (
    <>
      <Link to="/projects" className="mb-3 inline-block text-[13px] text-muted hover:text-ink">
        ← {t("project.back")}
      </Link>
      <PageHeader title={project.data?.name ?? <Skeleton className="h-9 w-72" />} />
      <Card className="mb-6 flex flex-wrap items-center justify-between gap-4 border-dashed p-5">
        <div className="max-w-[72ch]">
          <h2 className="font-semibold">{t("projects.upload")}</h2>
          <p className="text-[13px] text-muted">{t("projects.uploadHint")}</p>
          {upload.isError && (
            <p role="alert" className="mt-1 text-[13px] text-err">
              {upload.error.message}
            </p>
          )}
        </div>
        <input
          ref={input}
          type="file"
          multiple
          className="sr-only"
          aria-label={t("projects.upload")}
          data-testid="design-files"
          accept=".kicad_sch,.kicad_pcb,.kicad_pro,.csv,.xml,.brd,.pdf,.dxf,.dwg"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length) upload.mutate(files);
            e.target.value = "";
          }}
        />
        <Button
          variant="primary"
          onClick={() => input.current?.click()}
          disabled={upload.isPending}
        >
          {upload.isPending ? t("project.uploading") : t("project.choose")}
        </Button>
      </Card>

      <h2 className="mb-2 text-[16px] font-semibold">{t("projects.designs")}</h2>
      {designs.isPending ? (
        <Skeleton className="h-24" />
      ) : !designs.data?.items.length ? (
        <EmptyState>{t("projects.noDesigns")}</EmptyState>
      ) : (
        <Card>
          <ul>
            {designs.data.items.map((d) => (
              <DesignRow key={d.id} design={d} />
            ))}
          </ul>
        </Card>
      )}

      {projectRuns.length > 0 && (
        <>
          <h2 className="mt-8 mb-2 text-[16px] font-semibold">{t("project.runs")}</h2>
          <Card>
            <ul>
              {projectRuns.map((r) => (
                <li key={r.id} className="border-t border-line first:border-t-0">
                  <Link
                    to="/runs/$runId"
                    params={{ runId: r.id }}
                    className="flex items-center gap-3 px-5 py-3 hover:bg-paper"
                  >
                    <VariantBadge variant={r.variant} />
                    <RunStatus status={r.status} />
                    <span className="text-[13px] text-muted">{modelLabel(r.model_id)}</span>
                    <span className="ml-auto text-[12.5px] text-muted">
                      {formatDateTime(r.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </>
  );
}
