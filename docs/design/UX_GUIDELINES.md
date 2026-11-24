# UX/UI guidelines

Sources: the UX designer's recommendations (Mobbin + the frontend-design skill + shadcn/ui), the visual direction "fabrication drawing" (ADR-0019, mock-ups in `direction-v1/`), interaction patterns from **Homerun (web)** on Mobbin (`inspiration/mobbin-homerun-home-and-modal.png`), the earlier flow prototype (`prototype/v0-flow.html`).

> Inspiration, not a copy. We take **patterns** (layout, hierarchy, behaviours), not Homerun's graphics, illustrations, names or visual identity.

## 1. Tools
1. **The `frontend-design` skill** (Anthropic) – mandatory for any UI work. Its principles: plan tokens (colour, typography, layout) before code, avoid generic patterns, one bold thing per screen, the rest calm, critique of screenshots.
2. **shadcn/ui** – the component base (Radix + Tailwind), copied into `packages/ts/ui` and adapted to our tokens. Other libraries from the UX designer's list (Chakra UI, MUI, Mantine, Ant Design, HeroUI) – only as a source of patterns, **not** as dependencies (ADR-0014).
3. **Mobbin** – pattern references. If a paid account is available, connect the Mobbin MCP in Claude Code and before designing a screen look up 3–5 references (e.g. "empty state dashboard B2B", "create modal two-column form", "data table with side panel"). Record the links in the PR description.

## 2. Visual direction: fabrication drawing (ADR-0019)
The app looks like the **fabrication drawing of a PCB**, not like a typical SaaS. The user is a medical-device hardware engineer who reads such sheets every day. Reference mock-ups (target copy in PL): `direction-v1/start.png`, `run.png`, `bom.png`, `compare.png`. Homerun (§1, `inspiration/`) remains a source of **interaction** patterns only (organisation switcher, new-run modal with labels on the left, radio cards); its visual style no longer applies.

Three signature elements, each carrying information:
1. **Sheet with a zone frame** (`Sheet` in `@bomagent/ui`). Main surface of every working screen: `sheet` background, 1 px `ink` frame, second `line` frame 11 px outside, zones A–H on the top edge and 1–6 on the left (Martian Mono 10 px). The BOM item panel names the zone of the part ("Strefa B3, warstwa F.Cu") from the board placement when it is known. Below 900 px the zone frame is dropped.
2. **Title block** (`TitleBlock`) in the bottom-right corner of the sheet. Replaces stat cards and the plan pill: a large name cell (Archivo 125/800) + 6 label/value cells (project, revision, variant, model, input, date) and "Arkusz n z m". On Start: organisation state (plan, LLM budget, EU region, model, projects, members). Below 900 px it moves under the content.
3. **Board panel** (`MaskPanel`): dark-green solder mask, white "silkscreen", gold mounting holes in the corners, 18 px radius. Only where a conclusion is shown: the A/B verdict and the part location map. **At most one large panel per screen.**

Screens:
- **Start**: greeting "Cześć, {name}." + one sentence about what waits for a decision + "Przejrzyj uwagi". Device templates are one table of cells with shared edges (no separate cards); "Pusty projekt" has 135° hatching; the others have line drawings (1.4 px `ink` outline, one solid black element). Below: "Ostatnie przebiegi" with variant chips and status (icon + text). Title block with organisation state.
- **Live run**: two tracks like copper traces, A (violet) above B (green). Steps are vias: done = filled with a hole, current = ring with a pulsing centre (the only animation; off under `prefers-reduced-motion`), future = empty ring with a dashed segment. Step name above, time (mono) and executor (agent / rules / parser / generator) below. Counters (time, tokens, LLM calls, cost) per variant; "Zdarzenia na żywo" column (SSE) with the variant glyph.
- **BOM**: filters as buttons ("Wszystkie 61", "Z uwagami 3", "Decyzje LLM 14"), glyph legend, TanStack table with a 5 px provenance stripe. Selected row: `llm-bg` at 50 %. Side panel 360 px: designator (mono), MPN (Archivo 125/800), part map (`MaskPanel`), "Dlaczego ta część" with the datasheet quote (3 px `llm` left edge, link to the PDF page), "Wynik reguł" as a ✓/✕ list. Actions: "Zatwierdź pozycję", "Zmień MPN".
- **A/B comparison**: board panel with the verdict (gold mono silkscreen line, conclusion title, one sentence with numbers, metrics as bar pairs: A light violet `#B9B2FF`, B `silk`, values in mono) + list of lines where the variants differ (designator, MPN A and B stacked, one sentence "what happened", result). "Eksportuj do pracy (CSV)".

## 3. Tokens and typography
**Colours** (`apps/web/src/styles.css`, `@theme`):

| Token | Hex | Role |
|---|---|---|
| `vellum` | `#E6E9E4` | app background (tracing paper) |
| `sheet` | `#F4F6F2` | sheet, panels, tables |
| `ink` | `#1A1D1B` | text, sheet frame, primary button, focus ring |
| `muted` | `#59605B` | secondary text (5.9:1 on `sheet`) |
| `line` | `#B7BFB9` | construction lines, outer frame |
| `line-soft` | `#D4DAD5` | row separators |
| `mask` | `#0E4733` | board panel |
| `silk` | `#EEF2EA` | text on the board |
| `gold` | `#C9A43B` | mounting holes, selection on the board map, focus on the board. Never as text on a light background |
| `llm` / `llm-bg` | `#4B3BDB` / `#E7E4FB` | LLM agent decision, variant A |
| `rule` / `rule-bg` | `#17694A` / `#DCEDE3` | deterministic rule decision, variant B |
| `parser` | `#6E756F` | read from the design file (glyph only, not text) |
| `user` | `#1A1D1B` | a person decided |
| `error` / `error-bg` | `#B4321F` / `#F6E1DC` | error |
| `warn` | `#94580A` | to review |

**Provenance glyphs** (`ProvenanceGlyph`) – shape, not colour alone (A and B have similar lightness): LLM agent = hollow circle, rule = filled square (pad), parser = outlined diamond, person = filled disc. Same glyph in the table, timeline, log, legend and the thesis diagrams. Every BOM row has a 5 px stripe in the provenance colour on the left.

**Radii by hierarchy:** sheet 0, board panel 18 px, buttons and fields 4 px, chips 2 px. **No shadows** – depth comes from frames; the only exception is the dialog (`0 24px 64px -24px rgb(26 29 27 / .35)`).

**Typography:**
- **Archivo** variable (`@fontsource-variable/archivo/wdth.css`, axes `wdth` 62–125, `wght`) – one family in three widths: screen headings `wdth 125` / `wght 800` / `letter-spacing -0.015em` / `line-height 1.02` (greeting 64 px, screen title 40–44 px, panel heading 22 px); UI text `wdth 100`, 15 px / 1.5, labels 12.5–13 px; dense table columns (value, manufacturer) `wdth 86`.
- **Martian Mono** 400 – technical data only: MPN, designators, packages, times, costs, tokens; 12–12.5 px in tables, 17 px in counters. Never for labels or headings.

**Copy:** screen titles are sentences with a conclusion, not section names ("B waliduje, A wciąż dobiera części.", "Hybryda trafia częściej i kosztuje trzy razy mniej."). Labels in sentence case. The only all-caps text is the silkscreen on the board panel.

**Focus:** 2 px `ink` outline with 2 px offset; `gold` on the board panel.

**Without:** dark background with a neon accent (the "AI for PCB" category look); violet gradients, glow, "AI sparkles" ✨, 3D board illustrations; identical rounded cards with shadows (content is divided by sheet lines and title-block cells); all-caps labels above headings, 01/02/03 markers, "→" arrows in buttons, monospace in labels; colour as the only carrier of information; more than one board panel per screen.

**Inspiration (patterns, not copies):** Teenage Engineering OP-1 guide (device line drawings, warm grey, thin lines), Nominal (visible column grid, engineering tone), Oxide Computer ("FIG. 1" captions, hardware green, frames instead of shadows), Nothing (one strong accent on a calm background), Braintrust (LLM evaluation layout: properties, comparison, decision trace); KiCad / IPC (title block, sheet zones, layer colours). Anti-pattern: Flux, Quilter.

## 4. Screens (v1 minimum)
1. **Start** (as above).
2. **Projects** – list + upload (drag & drop of a folder, format detection, a message about format limitations).
3. **New run** – modal (as above).
4. **Live run** – a step timeline with dots in the provenance colour, time/token/cost counters, SSE; for the "Both" mode – two columns.
5. **BOM** – table (TanStack Table): provenance bar on the left of the row, "only with remarks" filters, inline editing saved as organization knowledge; item **side panel**: justification, citations from the knowledge base (with a link to the datasheet page), the result of each rule, change history.
6. **Variant comparison** – metrics vs the reference BOM, per-item differences.
7. **Knowledge base** – the organization's documents + an overview of the global corpus (read-only), indexing status.
8. **Audit log** – filtering by user, object, time; export.
9. **Organization settings** – members and roles, SSO (SAML/OIDC), API keys, limits and usage, data retention.
10. **Onboarding** – organization registration, domain verification, first project from a template.

## 5. Copy (UX writing)
Sentences written in plain language, from the user's perspective; the button says what will happen ("Run" – "Uruchom przebieg", "Export CSV" – "Eksportuj CSV"), the toast uses the same verb ("CSV exported" – "Wyeksportowano CSV"). Errors say what happened and how to fix it ("The .brd file is not supported directly. Export IPC-2581 from Allegro and upload it here." – "Plik .brd nie jest obsługiwany bezpośrednio. Wyeksportuj IPC-2581 z Allegro i wgraj go tutaj."). An empty state = an invitation to act. PL and EN from the start (i18n).

## 6. Quality
WCAG 2.2 AA (contrast, visible focus, full keyboard support, `prefers-reduced-motion`), responsiveness down to 375 px (BOM table scrolls horizontally, side panel as a drawer), loading states (skeletons), error and empty states for every list. Every screen: a Playwright screenshot in the PR + an axe test.
