import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { AlertTriangle } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Schemas } from "../lib/api";
import { type BomItem, lineProvenance, PROVENANCE_COLOR } from "../lib/provenance";

export function findingsFor(item: BomItem, findings: Schemas["Finding"][]): Schemas["Finding"][] {
  const refs = new Set(item.refdes);
  return findings.filter((f) => f.line === item.line || (f.refdes ?? []).some((r) => refs.has(r)));
}

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
  const [onlyFindings, setOnlyFindings] = useState(false);
  const data = useMemo(
    () =>
      onlyFindings ? bom.items.filter((i) => findingsFor(i, bom.findings ?? []).length) : bom.items,
    [bom, onlyFindings],
  );
  const columns = useMemo<ColumnDef<BomItem>[]>(
    () => [
      { id: "line", header: t("bom.columns.line"), accessorKey: "line" },
      {
        id: "refdes",
        header: t("bom.columns.refdes"),
        cell: ({ row }) => (
          <span className="font-mono text-[13px]">{row.original.refdes.join(", ")}</span>
        ),
      },
      { id: "qty", header: t("bom.columns.qty"), accessorKey: "quantity" },
      { id: "value", header: t("bom.columns.value"), accessorKey: "value" },
      {
        id: "footprint",
        header: t("bom.columns.footprint"),
        cell: ({ row }) => {
          const fp = row.original.package ?? row.original.footprint;
          return (
            <span title={fp} className="block max-w-[180px] truncate font-mono text-[13px]">
              {fp.includes(":") ? fp.split(":").pop() : fp}
            </span>
          );
        },
      },
      { id: "manufacturer", header: t("bom.columns.manufacturer"), accessorKey: "manufacturer" },
      {
        id: "mpn",
        header: t("bom.columns.mpn"),
        cell: ({ row }) => <span className="font-mono text-[13px]">{row.original.mpn || "–"}</span>,
      },
      {
        id: "notes",
        header: t("bom.columns.notes"),
        cell: ({ row }) => {
          const n = findingsFor(row.original, bom.findings ?? []).length;
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
    [t, bom.findings],
  );
  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel() });

  return (
    <div className="flex flex-col gap-3">
      <label className="inline-flex items-center gap-2 self-start">
        <input
          type="checkbox"
          checked={onlyFindings}
          onChange={(e) => setOnlyFindings(e.target.checked)}
          className="size-4 accent-ink"
        />
        {t("bom.onlyFindings")}
      </label>
      <div className="overflow-x-auto rounded-card border border-line bg-surface">
        <table className="w-full min-w-[860px] border-collapse text-left text-[14px]">
          <thead className="border-b border-line text-[13px] text-muted">
            {table.getHeaderGroups().map((g) => (
              <tr key={g.id}>
                <th scope="col" className="w-1 p-0">
                  <span className="sr-only">{t("bom.origin")}</span>
                </th>
                {g.headers.map((h) => (
                  <th key={h.id} scope="col" className="px-3 py-2.5 font-medium">
                    {flexRender(h.column.columnDef.header, h.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const kind = lineProvenance(row.original);
              const active = row.original.line === selected;
              return (
                <tr
                  key={row.id}
                  aria-selected={active}
                  tabIndex={0}
                  onClick={() => onSelect(row.original.line)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(row.original.line);
                    }
                  }}
                  className={`cursor-pointer border-b border-line last:border-0 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus ${
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
          </tbody>
        </table>
        {data.length === 0 ? (
          <p className="p-6 text-muted">{onlyFindings ? t("bom.noMatches") : t("bom.empty")}</p>
        ) : null}
      </div>
    </div>
  );
}
