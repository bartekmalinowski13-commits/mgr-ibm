# ADR-0019: Visual direction: fabrication drawing ("rysunek wykonawczy")

Status: Accepted · 2026-11-24 · supersedes the visual part (§2–§3) of `docs/design/UX_GUIDELINES.md` as written for ADR-0014 (Homerun direction)

## Context
The first UI (M5) followed patterns from Homerun: white cards with rounded corners, a stat-card row, a plan pill in the top bar, Bricolage Grotesque + IBM Plex. It works, but it reads like any B2B SaaS. The users are hardware engineers of medical devices; the category "AI for PCB" (Flux, Quilter) uses a dark UI with a neon accent. We want a look that is (a) native to the user's daily documents, (b) clearly different from that category and (c) carries information, not decoration – the same glyphs must work in the thesis diagrams.

## Decision
The application looks like the **fabrication drawing of a PCB** (KiCad/IPC drawing sheet). Three signature elements, each carrying data:

1. **Sheet with a zone frame** (`Sheet`): the main surface of every working screen; `sheet` background, 1 px `ink` frame, a second `line` frame 11 px outside it, zones A–H on the top edge and 1–6 on the left (Martian Mono 10 px). The BOM item panel names the zone and layer of the part on the board ("Strefa B3, warstwa F.Cu") when placement data is available.
2. **Title block** (`TitleBlock`) in the bottom-right corner of the sheet replaces stat cards and the plan pill: a large name cell (Archivo 125/800) + 6 label/value cells (project, revision, variant, model, input, date, "Arkusz n z m"). On Start it shows the organisation (plan, LLM budget, EU region, model).
3. **Board panel** (`MaskPanel`): one dark-green solder-mask panel with white silkscreen and gold mounting holes, used only where a conclusion is shown (A/B verdict, part location map). At most one large panel per screen.

Tokens, typography, glyphs and screen rules are in `docs/design/UX_GUIDELINES.md` §2–§3; reference mock-ups in `docs/design/direction-v1/`.

- Typography: **Archivo** variable (`wdth` 62–125, `wght`) as the only text family in three widths (125/800 headings, 100 UI text, 86 dense table columns); **Martian Mono** 400 only for technical data (MPN, designators, packages, times, costs, tokens). Bricolage Grotesque and IBM Plex are removed.
- Decision provenance is coded by **shape and colour**: agent LLM = hollow circle (violet), rule = filled square / pad (green), parser = outlined diamond (grey), person = filled disc (ink). The same glyph in the table, timeline, log, legend and thesis diagrams.
- Radii follow hierarchy (sheet 0, board panel 18 px, controls 4 px, chips 2 px); no shadows except the dialog.
- The only animation is the pulsing centre of the current via in the run timeline, off under `prefers-reduced-motion`.

## Consequences
- New base components in `packages/ts/ui`: `Sheet`, `TitleBlock`, `MaskPanel`, `ProvenanceGlyph`, `VariantChip`, `ViaTimeline`, with a preview page in the web app (`/design`, development only).
- Screens are rebuilt in the order BOM → Compare → Run → Start; existing behaviour (API calls, keyboard support, i18n) stays.
- The part location map needs board placement (x, y, layer, board outline) per BOM line. The API does not expose it today; the map reads optional fields and shows an empty state otherwise (assumption in `docs/DECISIONS_LOG.md`).
- The old tokens `paper`, `surface`, `focus` are replaced by `vellum`, `sheet` and an `ink` focus ring.

## Alternatives considered
- Keep the Homerun direction and only refine it – rejected: generic, does not use the users' own visual language.
- Dark "AI hardware" UI with a neon accent (Flux, Quilter) – rejected: the look of the whole category we want to stand apart from.
- Board panel as the background of every screen – rejected: the signature element stops working when it is everywhere.
