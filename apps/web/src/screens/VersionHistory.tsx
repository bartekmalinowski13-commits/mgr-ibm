import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call } from "../lib/api";
import { formatDate } from "../lib/format";
import { useSession } from "../lib/session";
import { LoadError, Skeleton } from "./common";

/** Version history of a run's BOM (generated version + user corrections) and the difference
 * between two chosen versions. */
export function VersionHistory({ runId, current }: { runId: string; current: number }) {
  const { t, i18n } = useTranslation();
  const { orgId } = useSession();
  const versions = useQuery({
    queryKey: ["bom-versions", orgId, runId, current],
    queryFn: () =>
      call(api.GET("/v1/runs/{run_id}/bom/versions", { params: { path: { run_id: runId } } })),
  });
  const [picked, setPicked] = useState<{ from?: number; to?: number }>({});
  const list = versions.data ?? [];
  const newest = list[0]?.version;
  const oldest = list[list.length - 1]?.version;
  const to = picked.to ?? newest;
  const from = picked.from ?? (list.length > 1 ? list[1]?.version : oldest);
  const diff = useQuery({
    queryKey: ["bom-diff", orgId, runId, from, to],
    queryFn: () =>
      call(
        api.GET("/v1/runs/{run_id}/bom/diff", {
          params: {
            path: { run_id: runId },
            query: { from_version: from as number, to_version: to as number },
          },
        }),
      ),
    enabled: list.length > 1 && from !== undefined && to !== undefined && from !== to,
  });

  if (versions.isPending) return <Skeleton rows={2} />;
  if (versions.isError) return <LoadError error={versions.error} />;

  const options = list.map((v) => (
    <option key={v.version} value={v.version}>
      {t("run.version", { version: v.version })}
    </option>
  ));
  const same =
    diff.data && !diff.data.added.length && !diff.data.removed.length && !diff.data.changed.length;

  return (
    <section aria-labelledby="history-title" className="flex flex-col gap-3">
      <h3 id="history-title" className="font-display text-xl font-bold">
        {t("history.title")}
      </h3>
      <ol className="divide-y divide-line rounded-control border border-line bg-sheet">
        {list.map((v) => (
          <li key={v.version} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5">
            <span className="font-medium">{t("run.version", { version: v.version })}</span>
            <span className="min-w-0 flex-1 truncate text-sm text-muted">
              {v.reason === "generated" ? t("history.generated") : v.reason}
            </span>
            <span className="text-sm text-muted">{formatDate(v.created_at, i18n.language)}</span>
            <span className="text-sm text-muted">{t("history.lines", { count: v.lines })}</span>
          </li>
        ))}
      </ol>
      {list.length > 1 ? (
        <div className="flex flex-col gap-3 rounded-control border border-line bg-sheet p-4">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              {t("history.from")}
              <select
                className="h-9 rounded-control border border-line bg-sheet px-2"
                value={from}
                onChange={(e) => setPicked({ ...picked, from: Number(e.target.value) })}
              >
                {options}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm">
              {t("history.to")}
              <select
                className="h-9 rounded-control border border-line bg-sheet px-2"
                value={to}
                onChange={(e) => setPicked({ ...picked, to: Number(e.target.value) })}
              >
                {options}
              </select>
            </label>
          </div>
          <div aria-live="polite">
            {from === to ? <p className="text-muted">{t("history.pickTwo")}</p> : null}
            {diff.isError ? <LoadError error={diff.error} /> : null}
            {same ? <p className="text-muted">{t("history.noChanges")}</p> : null}
            {diff.data && !same ? (
              <ul className="flex flex-col gap-2 text-sm">
                {diff.data.changed.map((c) => (
                  <li key={`c${c.line}`}>
                    <span className="font-medium">
                      {t("history.line", { line: c.line })} ({c.refdes.join(" ")})
                    </span>
                    <ul className="ml-4 list-disc">
                      {c.fields.map((f) => (
                        <li key={f.field}>
                          {f.field}: <del className="text-error">{f.before || "–"}</del>{" "}
                          <ins className="text-ok no-underline">{f.after || "–"}</ins>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
                {diff.data.added.map((i) => (
                  <li key={`a${i.line}`}>
                    {t("history.added", { line: i.line })} ({i.refdes.join(" ")})
                  </li>
                ))}
                {diff.data.removed.map((i) => (
                  <li key={`r${i.line}`}>
                    {t("history.removed", { line: i.line })} ({i.refdes.join(" ")})
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
