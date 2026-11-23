import { Button, EmptyState, Input } from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage } from "../lib/api";
import { formatDate } from "../lib/format";
import { useIntentKeys } from "../lib/idempotency";
import { usePageTitle } from "../lib/layout";
import { useIsOwner, useProjects } from "../lib/queries";
import { useToast } from "../lib/toast";
import { AddSamplesButton, LoadError, SampleBadge, Skeleton } from "./common";

export function ProjectsScreen() {
  const { t, i18n } = useTranslation();
  usePageTitle(t("projects.title"));
  const projects = useProjects();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const keys = useIntentKeys();
  const isOwner = useIsOwner();
  const noSamples = !!projects.data && !projects.data.items.some((p) => p.is_sample);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const body = { name: name.trim(), description: "" };
      const p = await call(
        api.POST("/v1/projects", {
          body,
          headers: { "Idempotency-Key": keys.keyFor("project", body) },
        }),
      );
      keys.done("project");
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      toast(t("projects.created"));
      await navigate({ to: "/projects/$projectId", params: { projectId: p.id } });
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <form
        onSubmit={create}
        className="flex flex-col gap-2 border border-ink bg-sheet p-4 sm:flex-row sm:items-end"
      >
        <label className="flex flex-1 flex-col gap-1.5 font-medium">
          {t("projects.name")}
          <Input
            ref={nameInput}
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={!!error}
          />
        </label>
        <Button type="submit" disabled={busy}>
          {t("projects.create")}
        </Button>
        {error ? (
          <p role="alert" className="text-sm text-status-error sm:basis-full">
            {error}
          </p>
        ) : null}
      </form>
      {isOwner && noSamples ? (
        <section
          aria-labelledby="samples-title"
          className="flex flex-col gap-3 border border-ink bg-sheet p-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <div>
            <h3 id="samples-title" className="font-display text-lg font-semibold">
              {t("samples.title")}
            </h3>
            <p className="max-w-[70ch] text-ink-soft">{t("samples.lead")}</p>
          </div>
          <AddSamplesButton />
        </section>
      ) : null}
      {projects.isPending ? (
        <Skeleton />
      ) : projects.isError ? (
        <LoadError error={projects.error} onRetry={() => void projects.refetch()} />
      ) : projects.data.items.length === 0 ? (
        <EmptyState
          title={t("empty.projects.title")}
          body={t("projects.empty")}
          action={
            <Button onClick={() => nameInput.current?.focus()}>{t("empty.projects.action")}</Button>
          }
        />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {projects.data.items.map((p) => (
            <li key={p.id}>
              <Link
                to="/projects/$projectId"
                params={{ projectId: p.id }}
                className="block border border-ink bg-sheet p-4 hover:bg-tint focus-visible:outline-2 focus-visible:outline-focus"
              >
                <span className="block font-display text-lg font-semibold">
                  {p.name}
                  {p.is_sample ? <SampleBadge /> : null}
                </span>
                <span className="block text-sm text-ink-soft">
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
