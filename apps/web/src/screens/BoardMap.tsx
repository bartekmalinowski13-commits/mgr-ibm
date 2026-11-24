import { MaskPanel } from "@bomagent/ui";
import { useTranslation } from "react-i18next";
import { placementOf, zoneOf } from "../lib/placement";
import type { BomItem } from "../lib/provenance";

/**
 * Where the selected part sits on the board (ADR-0019, the BOM screen's one board panel):
 * other placed parts as silkscreen outlines, the selected one in a gold frame.
 */
export function BoardMap({ item, items }: { item: BomItem; items: BomItem[] }) {
  const { t } = useTranslation();
  const here = placementOf(item);
  const placed = items.map((i) => ({ item: i, p: placementOf(i) })).filter((x) => x.p);
  const board = here?.board ?? placed[0]?.p?.board ?? { x0: 0, y0: 0, x1: 60, y1: 40 };
  const W = board.x1 - board.x0;
  const H = board.y1 - board.y0;
  const pad = Math.max(W, H) * 0.06;
  const pkg = item.package ?? item.footprint?.split(":").pop() ?? "";
  return (
    <figure className="flex flex-col gap-2">
      <MaskPanel as="div" className="px-6 py-5">
        <svg
          viewBox={`${board.x0 - pad} ${board.y0 - pad} ${W + 2 * pad} ${H + 2 * pad}`}
          role="img"
          aria-label={
            here
              ? t("panel.map.label", {
                  refdes: item.refdes.join(", "),
                  zone: zoneOf(here),
                  layer: here.layer,
                })
              : t("panel.map.none")
          }
          className="block h-auto w-full"
        >
          {/* a few copper traces for orientation, drawn in the board's own coordinates */}
          <g
            stroke="currentColor"
            strokeOpacity="0.35"
            strokeWidth={W / 220}
            fill="none"
            className="text-silk"
          >
            <path
              d={`M${board.x0 + W * 0.08} ${board.y0 + H * 0.3} H${board.x0 + W * 0.42} l${W * 0.04} ${H * 0.07} H${board.x0 + W * 0.7}`}
            />
            <path
              d={`M${board.x0 + W * 0.25} ${board.y0 + H * 0.75} H${board.x0 + W * 0.55} l${W * 0.05} -${H * 0.08} H${board.x0 + W * 0.92}`}
            />
          </g>
          {placed
            .filter((x) => x.item.line !== item.line)
            .map(({ item: other, p }) =>
              p ? (
                <g key={other.line} className="text-silk">
                  <rect
                    x={p.x - p.w / 2}
                    y={p.y - p.h / 2}
                    width={p.w}
                    height={p.h}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={W / 300}
                  />
                  <text
                    x={p.x}
                    y={p.y + p.h * 0.12}
                    textAnchor="middle"
                    fontSize={Math.min(p.h * 0.42, H / 14)}
                    fill="currentColor"
                    className="font-data"
                  >
                    {other.refdes[0]}
                  </text>
                </g>
              ) : null,
            )}
          {here ? (
            <g>
              <rect
                x={here.x - here.w / 2}
                y={here.y - here.h / 2}
                width={here.w}
                height={here.h}
                fill="none"
                stroke="var(--color-gold)"
                strokeWidth={W / 140}
              />
              <text
                x={here.x}
                y={here.y + here.h / 2 + H / 11}
                textAnchor="middle"
                fontSize={H / 14}
                fill="var(--color-silk)"
                className="font-data"
              >
                {item.refdes[0]}
              </text>
            </g>
          ) : (
            <text
              x={board.x0 + W / 2}
              y={board.y0 + H / 2}
              textAnchor="middle"
              fontSize={H / 12}
              fill="var(--color-silk)"
            >
              {t("panel.map.noneShort")}
            </text>
          )}
        </svg>
      </MaskPanel>
      <figcaption className="flex flex-wrap justify-between gap-x-4 text-[14px] text-muted">
        <span>
          {here
            ? t("panel.map.zone", { zone: zoneOf(here), layer: here.layer })
            : t("panel.map.none")}
        </span>
        {pkg ? (
          <span>{here?.sized ? t("panel.map.size", { pkg, w: here.w, h: here.h }) : pkg}</span>
        ) : null}
      </figcaption>
    </figure>
  );
}
