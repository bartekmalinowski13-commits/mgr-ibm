import { Button, Input, ProvenanceRail, ProvenanceSwatch, Textarea } from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { TFunction } from "i18next";
import { Check, TriangleAlert, X } from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage, type Schemas } from "../lib/api";
import { type BomItem, lineProvenance, type ProvenanceKind } from "../lib/provenance";
import { useKbDocuments } from "../lib/queries";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { findingsFor, rowStatus } from "./BomTable";

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
  const [announcement, setAnnouncement] = useState("");
  const panelRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset the form when another line is opened
  useEffect(() => {
    setValues(initial());
    setReason("");
    setError(undefined);
  }, [item.line]);
  // Focus moves into the panel on open and returns to the row that opened it on close.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    titleRef.current?.focus();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, []);
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
      setAnnouncement(t("panel.savedLive", { version: saved.version }));
      setReason("");
    } catch (err) {
      setError(problemMessage(err));
    }
  };
  // Below 2xl the panel is a drawer over the page: keep Tab inside it. At 2xl it is a side column.
  const trapTab = (e: ReactKeyboardEvent<HTMLElement>) => {
    if (e.key !== "Tab" || !panelRef.current) return;
    if (typeof window.matchMedia === "function" && window.matchMedia("(min-width: 1536px)").matches)
      return;
    const stops = [
      ...panelRef.current.querySelectorAll<HTMLElement>("button, input, textarea, [tabindex]"),
    ].filter((el) => el.tabIndex >= 0 && !(el as HTMLButtonElement).disabled);
    const first = stops[0];
    const last = stops[stops.length - 1];
    if (!first || !last) return;
    if (
      e.shiftKey &&
      (document.activeElement === first || document.activeElement === titleRef.current)
    ) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };
  const changed = EDITABLE.some((f) => values[f] !== (item[f] ?? ""));
  const kind = lineProvenance(item);
  const status = rowStatus(item, findings);
  // the rationale and citations shown first: the MPN decision is the one a reviewer checks
  const lead = provenance.find(([f]) => f === "mpn")?.[1] ?? provenance[0]?.[1];
  const citations = provenance.flatMap(([, p]) => p.citations ?? []);
  const tenantDocs = useKbDocuments(
    "tenant",
    citations.some((c) => c.scope === "tenant"),
  );
  const globalDocs = useKbDocuments(
    "global",
    citations.some((c) => c.scope === "global"),
  );
  const docTitle = (id: string, scope: "tenant" | "global") =>
    (scope === "tenant" ? tenantDocs : globalDocs).data?.items.find((d) => d.id === id)?.title ??
    t("panel.unknownDoc");
  const userChanges = provenance.filter(([, p]) => p.kind === "user");
  const editFirst = useRef<HTMLInputElement>(null);

  return (
    <aside
      ref={panelRef}
      onKeyDown={trapTab}
      aria-labelledby="panel-title"
      className={
        "fixed inset-x-0 bottom-0 z-30 max-h-[80vh] w-full overflow-y-auto border border-ink bg-sheet " +
        "md:inset-x-auto md:right-0 md:top-0 md:h-screen md:max-h-none md:w-[420px] md:border-y-0 md:border-r-0 " +
        "xl:sticky xl:top-0 xl:z-auto xl:h-auto xl:max-h-screen xl:w-[390px] xl:shrink-0 xl:self-start xl:border-y-0 xl:border-r-0"
      }
    >
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
      <header className="relative flex items-start justify-between gap-3 border-b border-ink py-4 pl-8 pr-4">
        <ProvenanceRail kind={kind} />
        <div className="min-w-0">
          <h3
            id="panel-title"
            ref={titleRef}
            tabIndex={-1}
            className="break-words font-display text-3xl font-semibold leading-none tracking-[-0.01em]"
          >
            {item.refdes.join(", ") || t("panel.title", { line: item.line })}
          </h3>
          <p className="mt-1.5 font-mono text-sm">{item.mpn || "–"}</p>
          <p
            className={`mt-1 text-sm font-semibold ${kind === "agent" ? "text-prov-llm" : kind === "rule" ? "text-prov-rule" : ""}`}
          >
            {t(`panel.decision.${kind}`)}
          </p>
        </div>
        <button
          type="button"
          aria-label={t("common.close")}
          onClick={onClose}
          className="shrink-0 p-1.5 hover:bg-tint"
        >
          <X size={18} aria-hidden />
        </button>
      </header>

      <div className="flex flex-col gap-5 p-5">
        <p className="text-sm text-ink-soft">
          {t("panel.title", { line: item.line })} · {t(`bom.status.${status}`)}
        </p>
        {lead?.rationale ? (
          <div>
            <h4 className="font-semibold">{t("panel.rationaleLabel")}</h4>
            <p className="mt-1 max-w-[65ch] leading-relaxed">{lead.rationale}</p>
          </div>
        ) : null}

        {citations.length ? (
          <div className="border border-ink p-3">
            <h4 className="text-sm text-ink-soft">{t("panel.source")}</h4>
            <ul className="mt-1.5 flex flex-col gap-2">
              {citations.map((c) => (
                <li key={c.chunk_id}>
                  {c.quote ? (
                    <q className="block underline decoration-cite decoration-2 underline-offset-4">
                      {c.quote}
                    </q>
                  ) : null}
                  <Link
                    to="/kb"
                    className="mt-1 inline-block text-sm font-medium underline underline-offset-4"
                  >
                    {c.page
                      ? t("panel.openSource", {
                          doc: docTitle(c.document_id, c.scope),
                          page: c.page,
                        })
                      : t("panel.openSourceNoPage", { doc: docTitle(c.document_id, c.scope) })}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div>
          <h4 className="font-semibold">{t("panel.rules")}</h4>
          {own.length ? (
            <ul className="mt-2 flex flex-col gap-2">
              {own.map((f) => (
                <li key={`${f.rule_id}-${f.message}`} className="flex gap-2 text-sm">
                  <TriangleAlert
                    size={14}
                    strokeWidth={2.75}
                    aria-hidden
                    className="mt-0.5 shrink-0 text-status-warn"
                  />
                  <span>
                    <span className="font-mono text-[13px]">{f.rule_id}</span>: {f.message}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 flex items-center gap-2 text-sm">
              <Check size={14} strokeWidth={2.75} aria-hidden /> {t("panel.rulesPassed")}
            </p>
          )}
        </div>

        <div>
          <h4 className="font-semibold">{t("panel.fields")}</h4>
          <ul className="mt-2 flex flex-col gap-3">
            {provenance.map(([field, p]) => (
              <li key={field} className="flex gap-3">
                <span className="mt-1">
                  <ProvenanceSwatch kind={p.kind as ProvenanceKind} />
                </span>
                <div className="min-w-0">
                  <p>
                    <span className="font-mono text-[13px]">{field}</span>: {origin(p, t)}
                  </p>
                  {p.rationale ? <p className="text-sm text-ink-soft">{p.rationale}</p> : null}
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h4 className="font-semibold">{t("panel.history")}</h4>
          {userChanges.length ? (
            <ul className="mt-2 flex flex-col gap-1.5 text-sm">
              {userChanges.map(([field, p]) => (
                <li key={field}>
                  {t("panel.historyUser", { field, user: p.kind === "user" ? p.user_id : "" })}
                  {p.rationale ? <span className="text-ink-soft"> – {p.rationale}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 text-sm text-ink-soft">{t("panel.historyEmpty")}</p>
          )}
        </div>

        <form onSubmit={save} className="border-t border-ink pt-4">
          <h4 className="font-semibold">{t("panel.edit")}</h4>
          <p className="mt-1 text-sm text-ink-soft">{t("panel.editLead")}</p>
          <div className="mt-3 grid gap-3">
            {EDITABLE.map((f) => (
              <label key={f} className="flex flex-col gap-1 text-sm font-medium">
                {t(`bom.columns.${f}`)}
                <Input
                  ref={f === "mpn" ? editFirst : undefined}
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
            <p role="alert" className="mt-2 text-sm text-status-error">
              {error}
            </p>
          ) : null}
          <div className="mt-3 flex">
            <Button type="submit" className="flex-1" disabled={!changed || !reason.trim()}>
              {t("panel.saveFix")}
            </Button>
            <Button
              variant="secondary"
              className="-ml-px flex-1"
              onClick={() => editFirst.current?.focus()}
            >
              {t("panel.change")}
            </Button>
          </div>
        </form>
      </div>
    </aside>
  );
}
