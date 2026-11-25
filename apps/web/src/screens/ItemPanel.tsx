import {
  Button,
  cn,
  Input,
  type Provenance,
  ProvenanceGlyph,
  StatusBadge,
  Textarea,
} from "@bomagent/ui";
import { useQueryClient } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import {
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { api, call, problemMessage, type Schemas } from "../lib/api";
import { ruleLabel } from "../lib/bomView";
import type { BomItem } from "../lib/provenance";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { BoardMap } from "./BoardMap";
import { findingsFor } from "./BomTable";

const matchesXl = () =>
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(min-width: 1280px)").matches;

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
  items,
  findings,
  onClose,
}: {
  runId: string;
  item: BomItem;
  /** all lines of the BOM, for the board map (defaults to this line only) */
  items?: BomItem[];
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
  const [editing, setEditing] = useState(false);
  const mpnRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset the form when another line is opened
  useEffect(() => {
    setValues(initial());
    setReason("");
    setError(undefined);
    setEditing(false);
  }, [item.line]);
  useEffect(() => {
    if (editing) mpnRef.current?.focus();
  }, [editing]);
  // Focus moves into the panel whenever a line is opened and returns, on close, to the row
  // that opened the line shown last.
  const opener = useRef<HTMLElement | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs for every newly opened line
  useEffect(() => {
    const active = document.activeElement as HTMLElement | null;
    if (active && !panelRef.current?.contains(active)) opener.current = active;
    titleRef.current?.focus();
  }, [item.line]);
  useEffect(
    () => () => {
      if (opener.current?.isConnected) opener.current.focus();
    },
    [],
  );
  // Below xl the panel covers the page: expose it as a modal dialog to assistive technology.
  const [drawer, setDrawer] = useState(() => !matchesXl());
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(min-width: 1280px)");
    const on = () => setDrawer(!mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
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
  // Below xl the panel is a drawer over the page: keep Tab inside it. At xl it is a side column.
  const trapTab = (e: ReactKeyboardEvent<HTMLElement>) => {
    if (e.key !== "Tab" || !panelRef.current) return;
    if (typeof window.matchMedia === "function" && window.matchMedia("(min-width: 1280px)").matches)
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
  const why = item.provenance?.mpn ?? item.provenance?.item;
  const whyKind = (why?.kind ?? "parser") as Provenance;
  const others = provenance.filter(([field]) => field !== "mpn" || !why);

  // a side column at xl, a modal drawer (dialog) over the page below it
  const Tag = drawer ? "div" : "aside";
  return (
    <Tag
      ref={panelRef as never}
      onKeyDown={trapTab}
      aria-label={`${t("panel.title", { line: item.line })}: ${item.refdes.join(", ")}`}
      role={drawer ? "dialog" : undefined}
      aria-modal={drawer ? true : undefined}
      className={
        "fixed inset-x-0 bottom-0 z-30 max-h-[85vh] w-full overflow-y-auto border-t border-ink bg-sheet px-5 pb-6 pt-5 shadow-dialog " +
        "md:inset-x-auto md:right-0 md:top-0 md:h-screen md:max-h-none md:w-[400px] md:border-l md:border-t-0 " +
        "xl:static xl:z-auto xl:h-auto xl:max-h-none xl:w-full xl:overflow-visible xl:border-l-0 xl:px-6 xl:shadow-none"
      }
    >
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
      <div className="flex items-start justify-between gap-3">
        <p className="pt-1.5 font-data text-[15px]" title={item.refdes.join(", ")}>
          {item.refdes.join(", ")}
        </p>
        <Button variant="secondary" size="sm" onClick={onClose}>
          {t("common.close")}
        </Button>
      </div>
      <h2
        id="panel-title"
        ref={titleRef}
        tabIndex={-1}
        className="mt-2 font-display text-[22px] [overflow-wrap:anywhere] focus-visible:outline-2 focus-visible:outline-ink"
      >
        {item.mpn || t("panel.noMpn")}
      </h2>
      <p className="mt-1 text-[15px] text-muted">
        {[item.manufacturer, item.description].filter(Boolean).join(", ") || item.value}
      </p>

      <div className="mt-5">
        <BoardMap item={item} items={items ?? [item]} />
      </div>

      {why ? (
        <section aria-labelledby="why-title" className="mt-6">
          <h3 id="why-title" className="flex items-center gap-2 text-[16px] font-semibold">
            <ProvenanceGlyph kind={whyKind} />
            {t("panel.why")}
          </h3>
          <p className="mt-1.5 text-[15px]">{why.rationale || origin(why, t)}</p>
          {why.rationale ? <p className="mt-1 text-[13px] text-muted">{origin(why, t)}</p> : null}
          {why.citations?.map((c) => (
            <blockquote
              key={c.chunk_id}
              className="mt-3 border-l-[3px] border-llm bg-llm-bg px-4 py-2.5 text-[15px]"
            >
              {c.quote ? <p>„{c.quote}”</p> : null}
              <cite className="mt-0.5 block text-[14px] not-italic font-semibold text-llm">
                {c.page ? t("panel.datasheetPage", { page: c.page }) : t("panel.datasheet")}
                {c.scope === "tenant" ? ` · ${t("panel.tenantSource")}` : ""}
              </cite>
            </blockquote>
          ))}
        </section>
      ) : null}

      <section aria-labelledby="rules-title" className="mt-6">
        <h3 id="rules-title" className="flex items-center gap-2 text-[16px] font-semibold">
          <ProvenanceGlyph kind="rule" />
          {t("panel.findings")}
        </h3>
        {own.length ? (
          <ul className="mt-2 flex flex-col gap-2">
            {own.map((f) => (
              <li key={`${f.rule_id}-${f.message}`} className="flex flex-col gap-0.5 text-[15px]">
                <StatusBadge
                  status={
                    f.severity === "error" ? "error" : f.severity === "info" ? "pending" : "warn"
                  }
                  label={ruleLabel(f.rule_id)}
                  className="self-start"
                />
                <span>{f.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2">
            <StatusBadge status="ok" label={t("panel.noFindings")} />
          </p>
        )}
      </section>

      {others.length ? (
        <section aria-labelledby="fields-title" className="mt-6">
          <h3 id="fields-title" className="text-[16px] font-semibold">
            {t("panel.fields")}
          </h3>
          <ul className="mt-2 flex flex-col gap-2">
            {others.map(([field, p]) => (
              <li key={field} className="flex gap-2.5 text-[14px]">
                <ProvenanceGlyph
                  kind={p.kind as Provenance}
                  label={t(`bom.provenance.${p.kind}`)}
                  className="mt-1"
                />
                <div className="min-w-0">
                  <p>
                    <span className="font-data text-[12.5px]">{field}</span>: {origin(p, t)}
                  </p>
                  {p.rationale && field !== "mpn" ? (
                    <p className="text-muted">{p.rationale}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {editing ? (
        <form onSubmit={save} className="mt-6 border-t border-line-soft pt-4">
          <h3 className="text-[16px] font-semibold">{t("panel.edit")}</h3>
          <p className="mt-1 text-[14px] text-muted">{t("panel.editLead")}</p>
          <div className="mt-3 grid gap-3">
            {EDITABLE.map((f) => (
              <label key={f} className="flex flex-col gap-1 text-[14px] font-semibold">
                {t(`bom.columns.${f}`)}
                <Input
                  ref={f === "mpn" ? mpnRef : undefined}
                  value={values[f]}
                  className={cn((f === "mpn" || f === "footprint") && "font-data text-[13px]")}
                  onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))}
                />
              </label>
            ))}
            <label className="flex flex-col gap-1 text-[14px] font-semibold">
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
            <p role="alert" className="mt-2 text-[14px] text-error">
              {error}
            </p>
          ) : null}
          <div className="mt-3 flex flex-wrap gap-3">
            <Button type="submit" disabled={!changed || !reason.trim()}>
              {t("panel.saveFix")}
            </Button>
            <Button variant="secondary" onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </Button>
          </div>
        </form>
      ) : (
        <div className="mt-6 flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => setEditing(true)}>
            {t("panel.changeMpn")}
          </Button>
        </div>
      )}
    </Tag>
  );
}
