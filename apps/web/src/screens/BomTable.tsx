import { ProvenanceRail, Segmented, type Status, StatusBadge } from "@bomagent/ui";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
  type VisibilityState,
} from "@tanstack/react-table";
import { observeElementRect, useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, ArrowUpDown, Columns3, Copy } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Schemas } from "../lib/api";
import { bomToCsv, type CsvColumn, matchesQuery } from "../lib/bomView";
import { type BomItem, lineProvenance } from "../lib/provenance";
import { useToast } from "../lib/toast";

export function findingsFor(item: BomItem, findings: Schemas["Finding"][]): Schemas["Finding"][] {
  const refs = new Set(item.refdes);
  return findings.filter((f) => f.line === item.line || (f.refdes ?? []).some((r) => refs.has(r)));
}

export type RowStatus = Extract<Status, "ok" | "warn" | "error">;

/** Worst severity among the findings of a line: error = needs a decision, warning/review = check. */
export function rowStatus(item: BomItem, findings: Schemas["Finding"][]): RowStatus {
  const own = findingsFor(item, findings);
  if (own.some((f) => f.severity === "error")) return "error";
  if (own.some((f) => f.severity === "warning" || f.severity === "review")) return "warn";
  return "ok";
}

type Filter = "all" | "findings" | "agent" | "rule";

const ROW_HEIGHT = 44;
const FALLBACK_HEIGHT = 600;
const COLUMN_IDS = [
  "line",
  "refdes",
  "qty",
  "value",
  "footprint",
  "manufacturer",
  "mpn",
  "notes",
] as const;

export function BomTable({
  bom,
  selected,
  onSelect,
}: {
  bom: Schemas["BomVersion"];
  selected?: number;
  onSelect: (line: number) => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [visibility, setVisibility] = useState<VisibilityState>({});
  const findings = bom.findings ?? [];
  const withFindings = useMemo(
    () => bom.items.filter((i) => findingsFor(i, findings).length).length,
    [bom.items, findings],
  );
  const data = useMemo(() => {
    if (filter === "findings") return bom.items.filter((i) => findingsFor(i, findings).length);
    if (filter === "agent" || filter === "rule")
      return bom.items.filter((i) => lineProvenance(i) === filter);
    return bom.items;
  }, [bom.items, findings, filter]);
  const columns = useMemo<ColumnDef<BomItem>[]>(
    () => [
      { id: "line", header: t("bom.columns.line"), accessorFn: (i) => i.line },
      {
        id: "refdes",
        header: t("bom.columns.refdes"),
        accessorFn: (i) => i.refdes.join(", "),
        sortingFn: "alphanumeric",
        cell: ({ row }) => (
          <span className="font-mono text-[13px]">{row.original.refdes.join(", ")}</span>
        ),
      },
      { id: "qty", header: t("bom.columns.qty"), accessorFn: (i) => i.quantity },
      {
        id: "value",
        header: t("bom.columns.value"),
        accessorFn: (i) => i.value ?? "",
        sortingFn: "alphanumeric",
      },
      {
        id: "footprint",
        header: t("bom.columns.footprint"),
        accessorFn: (i) => i.package ?? i.footprint ?? "",
        sortingFn: "alphanumeric",
        cell: ({ row }) => {
          const fp = row.original.package ?? row.original.footprint ?? "";
          return (
            <span title={fp} className="block max-w-[180px] truncate font-mono text-[13px]">
              {fp.includes(":") ? fp.split(":").pop() : fp}
            </span>
          );
        },
      },
      {
        id: "manufacturer",
        header: t("bom.columns.manufacturer"),
        accessorFn: (i) => i.manufacturer ?? "",
        sortingFn: "alphanumeric",
      },
      {
        id: "mpn",
        header: t("bom.columns.mpn"),
        accessorFn: (i) => i.mpn ?? "",
        sortingFn: "alphanumeric",
        cell: ({ row }) => <span className="font-mono text-[13px]">{row.original.mpn || "–"}</span>,
      },
      {
        id: "notes",
        header: t("bom.status.column"),
        accessorFn: (i) => findingsFor(i, findings).length,
        cell: ({ row }) => {
          const st = rowStatus(row.original, findings);
          return (
            <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-0.5">
              <StatusBadge status={st} label={t(`bom.status.${st}`)} />
              {row.original.dnp ? (
                <span className="text-sm text-ink-soft">{t("bom.status.dnp")}</span>
              ) : null}
            </span>
          );
        },
      },
    ],
    [t, findings],
  );
  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter: query, columnVisibility: visibility },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setVisibility,
    globalFilterFn: (row, _id, value: string) => matchesQuery(row.original, value),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });
  const rows = table.getRowModel().rows;

  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
    initialRect: { width: 1200, height: FALLBACK_HEIGHT },
    // An unmeasured (0px) viewport would render nothing; fall back to a plausible window.
    observeElementRect: (inst, cb) =>
      observeElementRect(inst, (r) => cb({ width: r.width, height: r.height || FALLBACK_HEIGHT })),
  });
  const virtualRows = virtualizer.getVirtualItems();
  const padTop = virtualRows.length ? (virtualRows[0]?.start ?? 0) : 0;
  const padBottom = virtualRows.length
    ? virtualizer.getTotalSize() - (virtualRows[virtualRows.length - 1]?.end ?? 0)
    : 0;
  const colSpan = table.getVisibleLeafColumns().length + 1;

  const copyCsv = async () => {
    const cols = table
      .getVisibleLeafColumns()
      .map((c) => c.id)
      .filter((id): id is CsvColumn => (COLUMN_IDS as readonly string[]).includes(id));
    try {
      await navigator.clipboard.writeText(
        bomToCsv(
          rows.map((r) => r.original),
          cols,
        ),
      );
      toast(t("bom.csvCopied", { count: rows.length }));
    } catch {
      toast(t("bom.csvFailed"), "error");
    }
  };

  const filtered = filter !== "all" || query.trim() !== "";
  const filterOptions: { value: Filter; label: string; count?: number }[] = [
    { value: "findings", label: t("bom.filters.findings"), count: withFindings },
    { value: "all", label: t("bom.filters.all"), count: bom.items.length },
    { value: "agent", label: t("bom.filters.agent") },
    { value: "rule", label: t("bom.filters.rule") },
  ];
  const control =
    "inline-flex h-9 items-center gap-1.5 border border-ink bg-sheet px-3 text-[13.5px] font-medium hover:bg-tint";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Segmented
          label={t("bom.filters.label")}
          options={filterOptions}
          value={filter}
          onChange={(v) => setFilter(filter === v && v !== "all" ? "all" : v)}
        />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("bom.search")}
          aria-label={t("bom.search")}
          className="h-9 min-w-[200px] flex-1 border border-ink bg-sheet px-3 sm:max-w-xs"
        />
        <details className="relative">
          <summary className={`${control} cursor-pointer list-none`}>
            <Columns3 size={16} aria-hidden /> {t("bom.columnsMenu")}
          </summary>
          <fieldset className="absolute z-20 mt-1 flex min-w-[180px] flex-col gap-1 border border-ink bg-sheet p-3">
            <legend className="sr-only">{t("bom.columnsMenu")}</legend>
            {table.getAllLeafColumns().map((c) => (
              <label key={c.id} className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={c.getIsVisible()}
                  onChange={c.getToggleVisibilityHandler()}
                  className="size-4 accent-ink"
                />
                {t(c.id === "notes" ? "bom.status.column" : `bom.columns.${c.id}`)}
              </label>
            ))}
          </fieldset>
        </details>
        <button type="button" onClick={() => void copyCsv()} className={control}>
          <Copy size={16} aria-hidden /> {t("bom.copyCsv")}
        </button>
        <span className="font-mono text-sm text-ink-soft" aria-live="polite">
          {t("bom.count", { shown: rows.length, total: bom.items.length })}
        </span>
      </div>
      <p className="text-sm text-ink-soft">{t("bom.legend")}</p>
      <section
        ref={scrollRef}
        // biome-ignore lint/a11y/noNoninteractiveTabindex: scrollable region must be focusable
        tabIndex={0}
        aria-label={t("bom.title")}
        className="max-h-[70vh] overflow-auto border-y border-ink bg-sheet"
      >
        <table className="w-full min-w-[860px] border-collapse text-left text-[14px]">
          <caption className="sr-only">{t("bom.sheetCaption")}</caption>
          <thead className="sticky top-0 z-10 bg-sheet text-[13px] text-ink-soft">
            {table.getHeaderGroups().map((g) => (
              <tr key={g.id}>
                <th scope="col" className="w-2 border-b border-ink p-0">
                  <span className="sr-only">{t("bom.origin")}</span>
                </th>
                {g.headers.map((h) => {
                  const dir = h.column.getIsSorted();
                  return (
                    <th
                      key={h.id}
                      scope="col"
                      className="border-b border-ink px-3 py-2 font-medium"
                      aria-sort={
                        dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"
                      }
                    >
                      <button
                        type="button"
                        onClick={h.column.getToggleSortingHandler()}
                        className="inline-flex items-center gap-1 font-medium hover:text-ink"
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {dir === "asc" ? (
                          <ArrowUp size={13} aria-hidden />
                        ) : dir === "desc" ? (
                          <ArrowDown size={13} aria-hidden />
                        ) : (
                          <ArrowUpDown size={13} aria-hidden className="opacity-40" />
                        )}
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {padTop > 0 ? (
              <tr aria-hidden style={{ height: padTop }}>
                <td colSpan={colSpan} />
              </tr>
            ) : null}
            {virtualRows.map((v) => {
              const row = rows[v.index];
              if (!row) return null;
              const kind = lineProvenance(row.original);
              const active = row.original.line === selected;
              return (
                <tr
                  key={row.id}
                  data-line={row.original.line}
                  aria-selected={active}
                  tabIndex={0}
                  style={{ height: ROW_HEIGHT }}
                  onClick={() => onSelect(row.original.line)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(row.original.line);
                    }
                  }}
                  className={`cursor-pointer border-b border-rule ${
                    active
                      ? "bg-tint outline outline-2 -outline-offset-2 outline-ink"
                      : "hover:bg-tint"
                  } ${row.original.dnp ? "text-ink-soft" : ""}`}
                >
                  <td className="relative w-2 p-0">
                    <ProvenanceRail kind={kind} label={t(`bom.provenance.${kind}`)} />
                  </td>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-3 py-2.5 align-top">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
            {padBottom > 0 ? (
              <tr aria-hidden style={{ height: padBottom }}>
                <td colSpan={colSpan} />
              </tr>
            ) : null}
          </tbody>
        </table>
        {rows.length === 0 ? (
          <div className="flex flex-col items-start gap-2 p-6">
            <p>{filtered ? t("bom.emptyFilter") : t("bom.empty")}</p>
            {filtered ? (
              <button
                type="button"
                className="font-medium underline underline-offset-4"
                onClick={() => {
                  setFilter("all");
                  setQuery("");
                }}
              >
                {t("bom.clearFilters")}
              </button>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
