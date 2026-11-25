import { SHEET_ZONES } from "@bomagent/ui";
import type { BomItem } from "./provenance";

/** Where a part sits on the board, read from optional `BomItem.fields` (DECISIONS_LOG 2026-11-24). */
export interface Placement {
  x: number;
  y: number;
  w: number;
  h: number;
  /** true when the size came from the design (not the default) */
  sized: boolean;
  layer: string;
  board: { x0: number; y0: number; x1: number; y1: number };
}

const num = (v: string | undefined): number | undefined => {
  if (v === undefined || v.trim() === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
};

export function placementOf(item: Pick<BomItem, "fields">): Placement | undefined {
  const f = item.fields ?? {};
  const x = num(f["pcb.x"]);
  const y = num(f["pcb.y"]);
  const box = (f["pcb.board"] ?? "").split(",").map((v) => num(v));
  const [x0, y0, x1, y1] = box;
  if (x === undefined || y === undefined) return undefined;
  if (x0 === undefined || y0 === undefined || x1 === undefined || y1 === undefined)
    return undefined;
  if (x1 <= x0 || y1 <= y0) return undefined;
  return {
    x,
    y,
    w: num(f["pcb.w"]) ?? 3,
    h: num(f["pcb.h"]) ?? 3,
    sized: num(f["pcb.w"]) !== undefined && num(f["pcb.h"]) !== undefined,
    layer: f["pcb.layer"] ?? "",
    board: { x0, y0, x1, y1 },
  };
}

/** Drawing-sheet zone of a point on the board: columns A–H left to right, rows 1–6 top down. */
export function zoneOf(p: Placement): string {
  const { columns, rows } = SHEET_ZONES;
  const fx = (p.x - p.board.x0) / (p.board.x1 - p.board.x0);
  const fy = (p.y - p.board.y0) / (p.board.y1 - p.board.y0);
  const clamp = (v: number, n: number) => Math.min(n - 1, Math.max(0, Math.floor(v * n)));
  return `${columns[clamp(fx, columns.length)]}${rows[clamp(fy, rows.length)]}`;
}
