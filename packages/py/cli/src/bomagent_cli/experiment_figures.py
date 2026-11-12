"""Static SVG figures for chapter 7 (no plotting dependency, deterministic output).

Figures are for print (the thesis is a DOCX), so they are static: every value a reader
needs is either printed on the figure or in the CSV tables written next to them. Colour
carries variant identity only, always together with a text label (A / B), from the
validated categorical palette (slots 1-2, checked for colour-vision deficiency and
contrast); text uses text tokens, gridlines are recessive hairlines.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from xml.sax.saxutils import escape

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
SERIES = {"A": "#2a78d6", "B": "#eb6834"}  # categorical slots 1-2 (validated)
FONT = "font-family=\"Inter, 'Helvetica Neue', Arial, sans-serif\""
VARIANT_NAMES = {"A": "A - LLM only", "B": "B - hybrid"}


@dataclass(frozen=True)
class Estimate:
    mean: float
    low: float
    high: float


def _num(v: float, digits: int = 2) -> str:
    if abs(v) >= 1000:
        return f"{v / 1000:.1f}K" if abs(v) < 1_000_000 else f"{v / 1_000_000:.1f}M"
    return f"{v:.{digits}f}"


def _svg(width: int, height: int, title: str, desc: str, body: list[str]) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
            f' viewBox="0 0 {width} {height}" role="img" {FONT}>',
            f"<title>{escape(title)}</title>",
            f"<desc>{escape(desc)}</desc>",
            f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
            f'<text x="16" y="26" font-size="15" font-weight="600" fill="{TEXT}">'
            f"{escape(title)}</text>",
            *body,
            "</svg>",
            "",
        ]
    )


def _legend(x: float, y: float, variants: Sequence[str]) -> list[str]:
    out = []
    for v in variants:
        out.append(f'<circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{SERIES[v]}"/>')
        out.append(
            f'<text x="{x + 15}" y="{y}" font-size="12" fill="{TEXT_2}">'
            f'<tspan font-weight="600" fill="{TEXT}">{v}</tspan>'
            f"{escape(VARIANT_NAMES[v][1:])}</text>"
        )
        x += 30 + 7 * len(VARIANT_NAMES[v])
    return out


def _x_axis(
    left: float,
    width: float,
    top: float,
    bottom: float,
    domain: tuple[float, float],
    ticks: Sequence[float],
    digits: int = 2,
) -> list[str]:
    lo, hi = domain
    out = []
    for t in ticks:
        x = left + (t - lo) / (hi - lo) * width
        out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="{GRID}"/>')
        out.append(
            f'<text x="{x:.1f}" y="{bottom + 16}" font-size="11" fill="{TEXT_2}"'
            f' text-anchor="middle">{_num(t, digits)}</text>'
        )
    return out


def dot_interval_chart(
    title: str,
    rows: Sequence[tuple[str, dict[str, Estimate]]],
    *,
    domain: tuple[float, float] = (0.0, 1.0),
    note: str = "Mean with 95 % bootstrap interval; higher is better unless marked (lower).",
) -> str:
    """One row per metric, one dot + interval per variant (rows offset, no overlap)."""
    variants = [v for v in ("A", "B") if any(v in est for _, est in rows)]
    label_w, plot_w, row_h = 210, 440, 44
    top = 64
    height = top + row_h * len(rows) + 56
    width = label_w + plot_w + 72
    left = label_w
    body = _legend(16, 48, variants)
    ticks = [domain[0] + i * (domain[1] - domain[0]) / 4 for i in range(5)]
    body += _x_axis(left, plot_w, top, top + row_h * len(rows), domain, ticks)
    lo, hi = domain

    def x_of(v: float) -> float:
        return left + (min(max(v, lo), hi) - lo) / (hi - lo) * plot_w

    for i, (label, estimates) in enumerate(rows):
        y0 = top + i * row_h
        body.append(
            f'<text x="{left - 12}" y="{y0 + row_h / 2 + 4}" font-size="12" fill="{TEXT}"'
            f' text-anchor="end">{escape(label)}</text>'
        )
        for j, v in enumerate(variants):
            est = estimates.get(v)
            if est is None or math.isnan(est.mean):
                continue
            y = y0 + 14 + j * 16
            if not (math.isnan(est.low) or math.isnan(est.high)) and est.low != est.high:
                body.append(
                    f'<line x1="{x_of(est.low):.1f}" y1="{y}" x2="{x_of(est.high):.1f}"'
                    f' y2="{y}" stroke="{SERIES[v]}" stroke-width="2" stroke-linecap="round"/>'
                )
            body.append(
                f'<circle cx="{x_of(est.mean):.1f}" cy="{y}" r="5" fill="{SERIES[v]}"'
                f' stroke="{SURFACE}" stroke-width="2"/>'
            )
            body.append(
                f'<text x="{left + plot_w + 8}" y="{y + 4}" font-size="11" fill="{TEXT_2}">'
                f'<tspan font-weight="600" fill="{TEXT}">{v}</tspan> {_num(est.mean, 3)}</text>'
            )
    body.append(
        f'<text x="16" y="{height - 14}" font-size="11" fill="{TEXT_2}">{escape(note)}</text>'
    )
    desc = "; ".join(
        f"{label}: "
        + ", ".join(f"{v} {_num(e.mean, 3)}" for v, e in est.items() if not math.isnan(e.mean))
        for label, est in rows
    )
    return _svg(width, height, title, desc, body)


def slope_chart(title: str, metric: str, pairs: Sequence[tuple[str, float, float]]) -> str:
    """Paired comparison: one line per design from A to B (the unit of the test)."""
    width, height = 520, 360
    top, bottom = 64, height - 56
    xa, xb = 170, 350
    values = [v for _, a, b in pairs for v in (a, b) if not math.isnan(v)]
    # no bars, so the axis may start above zero: zoom to the data (with some air)
    lo, hi = (min(values), max(values)) if values else (0.0, 1.0)
    pad = max((hi - lo) * 0.15, 0.02)
    lo, hi = max(lo - pad, 0.0), hi + pad

    def y_of(v: float) -> float:
        return bottom - (v - lo) / (hi - lo) * (bottom - top)

    body = _legend(16, 48, ["A", "B"])
    for i in range(5):
        t = lo + i * (hi - lo) / 4
        body.append(
            f'<line x1="{xa - 40}" y1="{y_of(t):.1f}" x2="{xb + 40}" y2="{y_of(t):.1f}"'
            f' stroke="{GRID}"/>'
        )
        body.append(
            f'<text x="{xa - 48}" y="{y_of(t) + 4:.1f}" font-size="11" fill="{TEXT_2}"'
            f' text-anchor="end">{_num(t, 3)}</text>'
        )
    for x, v in ((xa, "A"), (xb, "B")):
        body.append(
            f'<text x="{x}" y="{bottom + 22}" font-size="12" font-weight="600" fill="{TEXT}"'
            f' text-anchor="middle">{v}</text>'
        )
    # labels at the B end, pushed apart so they never overlap (>= 14 px)
    label_y: dict[str, float] = {}
    last = -math.inf
    for design, _, b in sorted((p for p in pairs if not math.isnan(p[2])), key=lambda p: -p[2]):
        y = max(y_of(b) + 4, last + 14)
        label_y[design] = y
        last = y
    for design, a, b in pairs:
        if math.isnan(a) or math.isnan(b):
            continue
        body.append(
            f'<line x1="{xa}" y1="{y_of(a):.1f}" x2="{xb}" y2="{y_of(b):.1f}"'
            f' stroke="{TEXT_2}" stroke-width="2"/>'
        )
        for x, v, val in ((xa, "A", a), (xb, "B", b)):
            body.append(
                f'<circle cx="{x}" cy="{y_of(val):.1f}" r="5" fill="{SERIES[v]}"'
                f' stroke="{SURFACE}" stroke-width="2"/>'
            )
        body.append(
            f'<text x="{xb + 12}" y="{label_y[design]:.1f}" font-size="11" fill="{TEXT_2}">'
            f"{escape(design)}</text>"
        )
    body.append(
        f'<text x="16" y="{height - 14}" font-size="11" fill="{TEXT_2}">'
        f"{escape(metric)} per design (mean over repetitions) - the unit of the paired test."
        "</text>"
    )
    desc = "; ".join(f"{d}: A {_num(a, 3)}, B {_num(b, 3)}" for d, a, b in pairs)
    return _svg(width, height, title, desc, body)


def bar_panels(title: str, panels: Sequence[tuple[str, dict[str, float]]]) -> str:
    """Small multiples, one scale per panel (never two scales on one axis)."""
    panel_w, gap, top = 220, 24, 64
    width = 16 + len(panels) * (panel_w + gap)
    height = top + 150
    body = _legend(16, 48, ["A", "B"])
    for p, (label, values) in enumerate(panels):
        x0 = 16 + p * (panel_w + gap)
        body.append(
            f'<text x="{x0}" y="{top + 12}" font-size="12" font-weight="600" fill="{TEXT}">'
            f"{escape(label)}</text>"
        )
        finite = [v for v in values.values() if not math.isnan(v)]
        peak = max(finite) if finite and max(finite) > 0 else 1.0
        bar_left, bar_w = x0 + 20, panel_w - 80
        body.append(
            f'<line x1="{bar_left}" y1="{top + 26}" x2="{bar_left}" y2="{top + 110}"'
            f' stroke="{GRID}"/>'
        )
        for j, v in enumerate(("A", "B")):
            val = values.get(v, math.nan)
            y = top + 34 + j * 36
            body.append(
                f'<text x="{x0}" y="{y + 16}" font-size="12" font-weight="600" fill="{TEXT}">'
                f"{v}</text>"
            )
            if math.isnan(val):
                continue
            w = max(bar_w * val / peak, 1.0)
            # square at the baseline, 4px rounded data end
            body.append(
                f'<path d="M{bar_left},{y} h{max(w - 4, 0):.1f} a4,4 0 0 1 4,4 v16'
                f' a4,4 0 0 1 -4,4 h{-max(w - 4, 0):.1f} z" fill="{SERIES[v]}"/>'
            )
            body.append(
                f'<text x="{bar_left + w + 6:.1f}" y="{y + 16}" font-size="11" fill="{TEXT_2}">'
                f"{_num(val, 4 if val < 1 else 1)}</text>"
            )
    desc = "; ".join(
        f"{label}: " + ", ".join(f"{v} {_num(x, 4)}" for v, x in vals.items())
        for label, vals in panels
    )
    return _svg(width, height, title, desc, body)
