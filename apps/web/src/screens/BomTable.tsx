import {
  cn,
  PROVENANCE_STRIPE,
  type Provenance,
  ProvenanceGlyph,
  ProvenanceLegend,
  StatusBadge,
} from "@bomagent/ui";
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
import {
  bomToCsv,
  type CsvColumn,
  compressRefdes,
  matchesQuery,
  ruleLabel,
  validationOf,
} from "../lib/bomView";
import { type BomItem, lineProvenance } from "../lib/provenance";
import { useToast } from "../lib/toast";

export function findingsFor(item: BomItem, findings: Schemas["Finding"][]): Schemas["Finding"][] {
  const refs = new Set(item.refdes);
  return findings.filter((f) => f.line === item.line || (f.refdes ?? []).some((r) => refs.has(r)));
}

const ROW_HEIGHT = 40;
type Filter = "all" | "findings" | "agent";
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
  const [visibility, setVisibility] = useState<VisibilityState>({ line: false });
  const findings = bom.findings ?? [];
  const withFindings = useMemo(
    () => bom.items.filter((i) => findingsFor(i, findings).length),
    [bom.items, findings],
  );
  const byAgent = useMemo(
    () => bom.items.filter((i) => lineProvenance(i) === "agent"),
    [bom.items],
  );
  const data = filter === "findings" ? withFindings : filter === "agent" ? byAgent : bom.items;
  const columns = useMemo<ColumnDef<BomItem>[]>(
    () => [
      {
        id: "line",
        header: t("bom.columns.line"),
        accessorFn: (i) => i.line,
        cell: ({ row }) => <span className="font-data text-[12px]">{row.original.line}</span>,
      },
      {
        id: "refdes",
        header: t("bom.columns.refdes"),
        accessorFn: (i) => i.refdes.join(", "),
        sortingFn: "alphanumeric",
        cell: ({ row }) => {
          const kind = lineProvenance(row.original);
          return (
            <span className="flex items-center gap-2.5">
              <ProvenanceGlyph kind={kind} label={t(`bom.provenance.${kind}`)} />
              <span className="font-data text-[12.5px]" title={row.original.refdes.join(", ")}>
                {compressRefdes(row.original.refdes)}
              </span>
            </span>
          );
        },
      },
      {
        id: "value",
        header: t("bom.columns.value"),
        accessorFn: (i) => i.value ?? "",
        sortingFn: "alphanumeric",
        cell: ({ row }) => <span className="font-narrow">{row.original.value || "—"}</span>,
      },
      {
        id: "footprint",
        header: t("bom.columns.footprint"),
        accessorFn: (i) => i.package ?? i.footprint ?? "",
        sortingFn: "alphanumeric",
        cell: ({ row }) => {
          const fp = row.original.package ?? row.original.footprint ?? "";
          return (
            <span
              title={fp}
              className="block max-w-[150px] truncate font-data text-[12.5px] text-muted"
            >
              {fp.includes(":") ? fp.split(":").pop() : fp}
            </span>
          );
        },
      },
      {
        id: "mpn",
        header: t("bom.columns.mpn"),
        accessorFn: (i) => i.mpn ?? "",
        sortingFn: "alphanumeric",
        cell: ({ row }) => (
          <span className="font-data text-[12.5px]">{row.original.mpn || "–"}</span>
        ),
      },
      {
        id: "manufacturer",
        header: t("bom.columns.manufacturer"),
        accessorFn: (i) => i.manufacturer ?? "",
        sortingFn: "alphanumeric",
        cell: ({ row }) => <span className="font-narrow">{row.original.manufacturer || "—"}</span>,
      },
      {
        id: "qty",
        header: t("bom.columns.qty"),
        accessorFn: (i) => i.quantity,
        cell: ({ row }) => (
          <span className="block text-right font-data text-[12.5px]">{row.original.quantity}</span>
        ),
      },
      {
        id: "notes",
        header: t("bom.columns.notes"),
        accessorFn: (i) => findingsFor(i, findings).length,
        cell: ({ row }) => {
          const own = findingsFor(row.original, findings);
          const state = validationOf(row.original, own);
          if (state === "error") {
            const first = own.find((f) => f.severity === "error");
            return <StatusBadge status="error" label={ruleLabel(first?.rule_id ?? "")} />;
          }
          if (state === "review")
            return <StatusBadge status="warn" label={t("bom.validation.review")} />;
          if (state === "dnp")
            return <span className="text-[14px] text-muted">{t("bom.dnp")}</span>;
          return <StatusBadge status="ok" label={t("bom.validation.ok")} />;
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
  const filters: { id: Filter; label: string; count: number; glyph?: Provenance }[] = [
    { id: "all", label: t("bom.filters.all"), count: bom.items.length },
    { id: "findings", label: t("bom.filters.findings"), count: withFindings.length },
    { id: "agent", label: t("bom.filters.agent"), count: byAgent.length, glyph: "agent" },
  ];
  const tool =
    "flex items-center gap-1.5 rounded-control border border-line bg-sheet px-2.5 py-1 text-[14px] hover:border-ink focus-visible:outline-2 focus-visible:outline-ink";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <fieldset className="flex flex-wrap gap-2.5">
          <legend className="sr-only">{t("bom.filters.label")}</legend>
          {filters.map((f) => (
            <button
              key={f.id}
              type="button"
              aria-pressed={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={cn(
                "inline-flex h-10 items-center gap-2 rounded-control border px-3.5 text-[15px] font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink",
                filter === f.id
                  ? "border-ink bg-ink text-sheet"
                  : "border-ink bg-sheet text-ink hover:bg-vellum",
              )}
            >
              {f.glyph ? (
                <ProvenanceGlyph
                  kind={f.glyph}
                  className={filter === f.id ? "text-sheet" : undefined}
                />
              ) : null}
              {f.label} <span className="tabular-nums">{f.count}</span>
            </button>
          ))}
        </fieldset>
        <ProvenanceLegend
          labels={{
            parser: t("bom.legend.parser"),
            rule: t("bom.legend.rule"),
            agent: t("bom.legend.agent"),
            user: t("bom.legend.user"),
          }}
        />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("bom.search")}
          aria-label={t("bom.search")}
          className="h-8 min-w-[180px] flex-1 rounded-control border border-line bg-sheet px-2.5 text-[14px] focus-visible:outline-2 focus-visible:outline-ink sm:max-w-[260px]"
        />
        <details className="relative">
          <summary className={cn(tool, "cursor-pointer list-none")}>
            <Columns3 size={15} aria-hidden /> {t("bom.columnsMenu")}
          </summary>
          <fieldset className="absolute z-20 mt-1 flex min-w-[180px] flex-col gap-1 rounded-control border border-ink bg-sheet p-3">
            <legend className="sr-only">{t("bom.columnsMenu")}</legend>
            {table.getAllLeafColumns().map((c) => (
              <label key={c.id} className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={c.getIsVisible()}
                  onChange={c.getToggleVisibilityHandler()}
                  className="size-4 accent-ink"
                />
                {t(`bom.columns.${c.id}`)}
              </label>
            ))}
          </fieldset>
        </details>
        <button type="button" onClick={() => void copyCsv()} className={tool}>
          <Copy size={15} aria-hidden /> {t("bom.copyCsv")}
        </button>
        <span className="text-[13px] text-muted" aria-live="polite">
          {t("bom.count", { shown: rows.length, total: bom.items.length })}
        </span>
      </div>
      <div ref={scrollRef} className="relative max-h-[70vh] overflow-auto">
        <table className="w-full min-w-[720px] border-collapse text-left text-[14.5px]">
          <thead className="sticky top-0 z-10 bg-sheet text-[14px] text-muted shadow-[inset_0_-1px_0_var(--color-ink)]">
            {table.getHeaderGroups().map((g) => (
              <tr key={g.id}>
                <th scope="col" className="w-[5px] p-0">
                  <span className="sr-only">{t("bom.origin")}</span>
                </th>
                {g.headers.map((h) => {
                  const dir = h.column.getIsSorted();
                  return (
                    <th
                      key={h.id}
                      scope="col"
                      className={cn(
                        "px-3 py-2.5 font-normal",
                        h.column.id === "qty" && "text-right",
                      )}
                      aria-sort={
                        dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"
                      }
                    >
                      <button
                        type="button"
                        onClick={h.column.getToggleSortingHandler()}
                        className="inline-flex items-center gap-1 hover:text-ink focus-visible:outline-2 focus-visible:outline-ink"
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {dir === "asc" ? (
                          <ArrowUp size={13} aria-hidden />
                        ) : dir === "desc" ? (
                          <ArrowDown size={13} aria-hidden />
                        ) : (
                          <ArrowUpDown
                            size={12}
                            aria-hidden
                            className="opacity-0 group-hover:opacity-40"
                          />
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
                  className={cn(
                    "group cursor-pointer border-b border-line-soft focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ink",
                    active ? "bg-llm-bg/50" : "hover:bg-vellum/50",
                    row.original.dnp && "text-muted",
                  )}
                >
                  <td className="relative w-[5px] p-0">
                    <span
                      aria-hidden
                      className={cn("absolute inset-y-0 left-0 w-[5px]", PROVENANCE_STRIPE[kind])}
                    />
                  </td>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="whitespace-nowrap px-2.5 py-2">
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
          <p className="px-3 py-6 text-muted">{filtered ? t("bom.noMatches") : t("bom.empty")}</p>
        ) : null}
      </div>
    </div>
  );
}
