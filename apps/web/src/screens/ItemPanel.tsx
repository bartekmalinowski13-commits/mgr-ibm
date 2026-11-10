import { Button, Input, Textarea } from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { X } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage, type Schemas } from "../lib/api";
import { type BomItem, PROVENANCE_COLOR, type ProvenanceKind } from "../lib/provenance";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { findingsFor } from "./BomTable";

const EDITABLE = ["mpn", "manufacturer", "value", "footprint"] as const;
type Editable = (typeof EDITABLE)[number];

function origin(p: Schemas["Provenance"], t: TFunction): string {
  switch (p.kind) {
    case "rule":
      return t("panel.rule", { rule: p.rule_id, pack: p.rule_pack, version: p.rule_pack_version });
    case "agent":
      return t("panel.agent", { agent: p.agent, model: p.model_id });
    case "user":
      return t("panel.user", { user: p.user_id });
    default:
      return t("panel.parser", { parser: p.parser });
  }
}

export function ItemPanel({
  runId,
  item,
  findings,
  onClose,
}: {
  runId: string;
  item: BomItem;
  findings: Schemas["Finding"][];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { orgId } = useSession();
  const toast = useToast();
  const queryClient = useQueryClient();
  const initial = () =>
    Object.fromEntries(EDITABLE.map((f) => [f, item[f] ?? ""])) as Record<Editable, string>;
  const [values, setValues] = useState(initial);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string>();
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset the form when another line is opened
  useEffect(() => {
    setValues(initial());
    setReason("");
    setError(undefined);
  }, [item.line]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const own = findingsFor(item, findings);
  const provenance = Object.entries(item.provenance ?? {});

  const save = async (e: FormEvent) => {
    e.preventDefault();
    const changes = Object.fromEntries(
      EDITABLE.filter((f) => values[f] !== (item[f] ?? "")).map((f) => [f, values[f]]),
    );
    try {
      const saved = await call(
        api.PATCH("/v1/runs/{run_id}/bom/items/{line}", {
          params: { path: { run_id: runId, line: item.line } },
          body: { ...changes, reason },
        }),
      );
      queryClient.setQueryData(["bom", orgId, runId], saved);
      toast(t("panel.saved", { version: saved.version }));
      setReason("");
    } catch (err) {
      setError(problemMessage(err));
    }
  };
  const changed = EDITABLE.some((f) => values[f] !== (item[f] ?? ""));

  return (
    <aside
      aria-labelledby="panel-title"
      className={
        "fixed inset-x-0 bottom-0 z-30 max-h-[80vh] w-full overflow-y-auto rounded-t-panel border border-line bg-surface p-5 shadow-dialog " +
        "md:inset-x-auto md:right-0 md:top-0 md:max-h-none md:h-screen md:w-[420px] md:rounded-none md:border-y-0 md:border-r-0 " +
        "2xl:sticky 2xl:top-20 2xl:z-auto 2xl:h-auto 2xl:max-h-[calc(100vh-6rem)] 2xl:w-[400px] 2xl:shrink-0 2xl:rounded-panel 2xl:border 2xl:shadow-none"
      }
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id="panel-title" className="font-display text-xl font-bold">
            {t("panel.title", { line: item.line })}
          </h3>
          <p className="font-mono text-[13px] text-muted">{item.refdes.join(", ")}</p>
        </div>
        <button
          type="button"
          aria-label={t("common.close")}
          onClick={onClose}
          className="rounded-control p-1.5 text-muted hover:bg-paper hover:text-ink"
        >
          <X size={18} aria-hidden />
        </button>
      </div>

      <h4 className="mt-5 font-medium">{t("panel.fields")}</h4>
      <ul className="mt-2 flex flex-col gap-3">
        {provenance.map(([field, p]) => (
          <li key={field} className="flex gap-3">
            <span
              aria-hidden
              className={`mt-1.5 size-2.5 shrink-0 rounded-full ${PROVENANCE_COLOR[p.kind as ProvenanceKind]}`}
            />
            <div className="min-w-0">
              <p>
                <span className="font-mono text-[13px]">{field}</span>: {origin(p, t)}
              </p>
              {p.rationale ? <p className="text-sm text-muted">{p.rationale}</p> : null}
              {p.citations?.length ? (
                <ul className="mt-1 flex flex-col gap-1">
                  {p.citations.map((c) => (
                    <li key={c.chunk_id} className="rounded-control bg-paper px-2.5 py-1.5 text-sm">
                      {c.quote ? <q>{c.quote}</q> : null}{" "}
                      <span className="text-muted">
                        ({c.scope}
                        {c.page ? `, ${t("panel.page", { page: c.page })}` : ""})
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      <h4 className="mt-5 font-medium">{t("panel.findings")}</h4>
      {own.length ? (
        <ul className="mt-2 flex flex-col gap-2">
          {own.map((f) => (
            <li
              key={`${f.rule_id}-${f.message}`}
              className="rounded-control border border-warn/30 bg-warn/5 px-3 py-2 text-sm"
            >
              <span className="font-mono text-[13px]">{f.rule_id}</span> – {f.message}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-muted">{t("panel.noFindings")}</p>
      )}

      <form onSubmit={save} className="mt-5 border-t border-line pt-4">
        <h4 className="font-medium">{t("panel.edit")}</h4>
        <p className="mt-1 text-sm text-muted">{t("panel.editLead")}</p>
        <div className="mt-3 grid gap-3">
          {EDITABLE.map((f) => (
            <label key={f} className="flex flex-col gap-1 text-sm font-medium">
              {t(`bom.columns.${f}`)}
              <Input
                value={values[f]}
                className={f === "mpn" || f === "footprint" ? "font-mono" : undefined}
                onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))}
              />
            </label>
          ))}
          <label className="flex flex-col gap-1 text-sm font-medium">
            {t("panel.reason")}
            <Textarea
              required
              maxLength={1000}
              value={reason}
              placeholder={t("panel.reasonHint")}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
        </div>
        {error ? (
          <p role="alert" className="mt-2 text-sm text-error">
            {error}
          </p>
        ) : null}
        <Button type="submit" className="mt-3" disabled={!changed || !reason.trim()}>
          {t("panel.saveFix")}
        </Button>
      </form>
    </aside>
  );
}
