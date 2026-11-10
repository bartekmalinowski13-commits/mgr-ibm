import { idempotencyKey } from "@bomagent/api-client";
import { Button, Input } from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage } from "../lib/api";
import { formatDate } from "../lib/format";
import { usePageTitle } from "../lib/layout";
import { useProjects } from "../lib/queries";
import { useToast } from "../lib/toast";
import { LoadError, Skeleton } from "./common";

export function ProjectsScreen() {
  const { t, i18n } = useTranslation();
  usePageTitle(t("projects.title"));
  const projects = useProjects();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState("");
  const [error, setError] = useState<string>();

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      const p = await call(
        api.POST("/v1/projects", {
          body: { name: name.trim(), description: "" },
          headers: { "Idempotency-Key": idempotencyKey() },
        }),
      );
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      toast(t("projects.created"));
      await navigate({ to: "/projects/$projectId", params: { projectId: p.id } });
    } catch (err) {
      setError(problemMessage(err));
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <form
        onSubmit={create}
        className="flex flex-col gap-2 rounded-card border border-line bg-surface p-4 sm:flex-row sm:items-end"
      >
        <label className="flex flex-1 flex-col gap-1.5 font-medium">
          {t("projects.name")}
          <Input
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={!!error}
          />
        </label>
        <Button type="submit">{t("projects.create")}</Button>
        {error ? (
          <p role="alert" className="text-sm text-error sm:basis-full">
            {error}
          </p>
        ) : null}
      </form>
      {projects.isPending ? (
        <Skeleton />
      ) : projects.isError ? (
        <LoadError error={projects.error} onRetry={() => void projects.refetch()} />
      ) : projects.data.items.length === 0 ? (
        <p className="max-w-[70ch] rounded-card border border-dashed border-line p-6 text-muted">
          {t("projects.empty")}
        </p>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {projects.data.items.map((p) => (
            <li key={p.id}>
              <Link
                to="/projects/$projectId"
                params={{ projectId: p.id }}
                className="block rounded-card border border-line bg-surface p-4 hover:border-ink/40 focus-visible:outline-2 focus-visible:outline-focus"
              >
                <span className="block font-display text-lg font-bold">{p.name}</span>
                <span className="block text-sm text-muted">
                  {formatDate(p.created_at, i18n.language)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
