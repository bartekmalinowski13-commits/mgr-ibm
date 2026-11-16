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
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, Columns3, Copy } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Schemas } from "../lib/api";
import { bomToCsv, type CsvColumn, matchesQuery } from "../lib/bomView";
import { type BomItem, lineProvenance, PROVENANCE_COLOR } from "../lib/provenance";
import { useToast } from "../lib/toast";

export function findingsFor(item: BomItem, findings: Schemas["Finding"][]): Schemas["Finding"][] {
  const refs = new Set(item.refdes);
  return findings.filter((f) => f.line === item.line || (f.refdes ?? []).some((r) => refs.has(r)));
}

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
  const [onlyFindings, setOnlyFindings] = useState(false);
  const [query, setQuery] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [visibility, setVisibility] = useState<VisibilityState>({});
  const findings = bom.findings ?? [];
  const data = useMemo(
    () => (onlyFindings ? bom.items.filter((i) => findingsFor(i, findings).length) : bom.items),
    [bom.items, findings, onlyFindings],
  );
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
        header: t("bom.columns.notes"),
        accessorFn: (i) => findingsFor(i, findings).length,
        cell: ({ row }) => {
          const n = findingsFor(row.original, findings).length;
          return n ? (
            <span className="inline-flex items-center gap-1 text-warn">
              <AlertTriangle size={14} aria-hidden /> {n}
            </span>
          ) : row.original.dnp ? (
            <span className="text-muted">{t("bom.dnp")}</span>
          ) : null;
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

  const filtered = onlyFindings || query.trim() !== "";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("bom.search")}
          aria-label={t("bom.search")}
          className="min-w-[200px] flex-1 rounded-control border border-line bg-surface px-3 py-1.5 focus-visible:outline-2 focus-visible:outline-focus sm:max-w-xs"
        />
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={onlyFindings}
            onChange={(e) => setOnlyFindings(e.target.checked)}
            className="size-4 accent-ink"
          />
          {t("bom.onlyFindings")}
        </label>
        <details className="relative">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-control border border-line bg-surface px-3 py-1.5 focus-visible:outline-2 focus-visible:outline-focus">
            <Columns3 size={16} aria-hidden /> {t("bom.columnsMenu")}
          </summary>
          <fieldset className="absolute z-20 mt-1 flex min-w-[180px] flex-col gap-1 rounded-card border border-line bg-surface p-3 shadow-dialog">
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
        <button
          type="button"
          onClick={() => void copyCsv()}
          className="flex items-center gap-1.5 rounded-control border border-line bg-surface px-3 py-1.5 hover:border-ink/40 focus-visible:outline-2 focus-visible:outline-focus"
        >
          <Copy size={16} aria-hidden /> {t("bom.copyCsv")}
        </button>
        <span className="text-sm text-muted" aria-live="polite">
          {t("bom.count", { shown: rows.length, total: bom.items.length })}
        </span>
      </div>
      <div
        ref={scrollRef}
        className="max-h-[70vh] overflow-auto rounded-card border border-line bg-surface"
      >
        <table className="w-full min-w-[860px] border-collapse text-left text-[14px]">
          <thead className="sticky top-0 z-10 border-b border-line bg-surface text-[13px] text-muted">
            {table.getHeaderGroups().map((g) => (
              <tr key={g.id}>
                <th scope="col" className="w-1 p-0">
                  <span className="sr-only">{t("bom.origin")}</span>
                </th>
                {g.headers.map((h) => {
                  const dir = h.column.getIsSorted();
                  return (
                    <th
                      key={h.id}
                      scope="col"
                      className="px-3 py-2.5 font-medium"
                      aria-sort={
                        dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"
                      }
                    >
                      <button
                        type="button"
                        onClick={h.column.getToggleSortingHandler()}
                        className="inline-flex items-center gap-1 font-medium hover:text-ink focus-visible:outline-2 focus-visible:outline-focus"
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
                  className={`cursor-pointer border-b border-line focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus ${
                    active ? "bg-paper" : "hover:bg-paper/60"
                  } ${row.original.dnp ? "text-muted" : ""}`}
                >
                  <td className="relative w-1 p-0">
                    <span
                      className={`absolute inset-y-0 left-0 w-1 ${PROVENANCE_COLOR[kind]}`}
                      title={t(`bom.provenance.${kind}`)}
                    />
                    <span className="sr-only">{t(`bom.provenance.${kind}`)}</span>
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
          <p className="p-6 text-muted">{filtered ? t("bom.noMatches") : t("bom.empty")}</p>
        ) : null}
      </div>
    </div>
  );
}
