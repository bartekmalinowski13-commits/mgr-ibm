# UX/UI guidelines

Sources: the visual identity canvas "BOM Agent" (section 3), the UX designer's recommendations (Mobbin + the frontend-design skill + shadcn/ui), inspiration from **Homerun (web)** on Mobbin (`inspiration/mobbin-homerun-home-and-modal.png`), the earlier flow prototype (`prototype/v0-flow.html`).

> Inspiration, not a copy. We take **patterns** (layout, hierarchy, behaviours), not Homerun's graphics, illustrations, names or visual identity.

## 1. Tools
1. **The `frontend-design` skill** (Anthropic) – mandatory for any UI work. Its principles: plan tokens (colour, typography, layout) before code, avoid generic patterns, one bold thing per screen, the rest calm, critique of screenshots.
2. **shadcn/ui** – the component base (Radix + Tailwind), copied into `packages/ts/ui` and adapted to our tokens. Other libraries from the UX designer's list (Chakra UI, MUI, Mantine, Ant Design, HeroUI) – only as a source of patterns, **not** as dependencies (ADR-0014).
3. **Mobbin** – pattern references. If a paid account is available, connect the Mobbin MCP in Claude Code and before designing a screen look up 3–5 references (e.g. "empty state dashboard B2B", "create modal two-column form", "data table with side panel"). Record the links in the PR description.

## 2. What we take from Homerun (screenshot analysis)
| Pattern in Homerun | How we apply it in BOM Agent |
|---|---|
| Left sidebar: organization switcher at the top (avatar + name + arrow), icons + labels, "Your jobs" section and the organization name, brand logo at the bottom | Sidebar: **organization switcher** (multi-tenant!), main navigation: Start (Start), Notifications (Powiadomienia), Search (Szukaj), **+ New run** (+ Nowy przebieg; an action in the navigation); section "Your projects" (Twoje projekty; recent); organization section: Projects (Projekty), Runs (Przebiegi), BOMs (Zestawienia BOM), Knowledge base (Baza wiedzy), Rules (Reguły), Audit log (Log audytu), Analytics (Analizy), Settings (Ustawienia) |
| Top bar: page title on the left, on the right a "15 days left in your trial · View plans" pill | Title/breadcrumb; on the right a plan pill (e.g. "Pilot: 15 days · View plans" – "Pilot: 15 dni · Zobacz plany") and LLM quota usage |
| Large, heavy greeting "Hi there Sam" – typography as a graphic element | "Hello, Bartek" ("Cześć, Bartek") in IBM Plex Sans Condensed 600; the only place on the screen with typography this large |
| "Create a new job" panel with a template carousel ("No template" card with a plus + cards with covers), closed with a cross | **"New BOM run"** panel (Nowy przebieg BOM): an "Empty project" card (+) (Pusty projekt) and templates of example devices (wearable ECG, pulse oximeter, EEG amplifier, infusion pump…) with **our own** covers (SVG illustrations themed on PCBs/sensors) |
| A row of stat cards that in the empty state are an invitation ("No active jobs", "No candidates", "1 to-do") | Cards: active runs, items to review, open validation remarks, projects – **empty states always with an action**, not an empty "0" number |
| "Guides" section with illustrated cards | "Guides" (Przewodniki): how to prepare a KiCad project, how variants A and B differ, the IEC 60601 checklist, how to export IPC-2581 from Altium/Allegro |
| "Create new job" modal: labels on the left, fields on the right, asterisk for required, selects, **radio cards with mini illustrations** ("Job post and application form" / "Only application form"), footer: Cancel + Continue | **"New run"** modal (Nowy przebieg): Name*, Project (select / upload), Device requirements (application part, power supply), Model (closed / open-weight), **Variant as radio cards with a mini pipeline diagram** (A: 100% LLM / B: hybrid / Both + comparison); footer: Cancel (Anuluj) + Next (Dalej) |
| Warm, light background, white cards with a delicate border, large card rounding, few shadows | **Not taken.** White sheet, 1px `ink` outlines, radius 0, no shadows (section 3) |
| Purple accent (trial) and green (primary) | **Not taken.** Violet and green mean provenance only (section 3); the primary action is black |

## 3. Visual identity: a technical drawing sheet (ADR-0020)
BOM Agent looks like an engineering document that somebody checks and signs, not a consumer app. The visual reference is the canvas "BOM Agent" (artboards *brand*, *zestawienie*, *przebieg i porównanie*); where this text and the canvas differ in spacing, the canvas wins, where they differ in meaning, this text wins.

**Shape:** everything is square (radius 0), 1px `ink` outlines, dense tables, layout made of lines instead of shadowed cards. **No shadows, no gradients (except the hatched LLM rail), no rounded corners.** Nothing from the author's other application (soft, rounded, warm) is carried over: no cream/terracotta/butter colours, no Fraunces, no large radii.

**Surfaces:** a white *sheet* with a 1px `ink` outline on a grey *desk* (`#B4B9B4`) on the document screens (BOM, run, comparison); other screens are plain white. The sidebar is black (`#111413`) with white text. No text is placed directly on the desk.

**Tokens** (CSS custom properties in `apps/web/src/styles.css`, Tailwind `@theme`; the same names are used in `packages/ts/ui`):
```css
--color-sheet: #FFFFFF;      /* the sheet, working background */
--color-desk: #B4B9B4;       /* background around the sheet */
--color-ink: #111413;        /* text, outlines, primary action, sidebar */
--color-ink-soft: #4D5450;   /* secondary text */
--color-rule: #C9CCC7;       /* thin lines inside tables */
--color-prov-llm: #5B3FD6;   /* decision of an LLM agent, variant A */
--color-prov-rule: #0C6B4B;  /* decision of a rule, variant B */
--color-cite: #9A6F00;       /* underline of a quote from the source */
--color-status-warn: #8A5A00;
--color-status-error: #C2362B; /* "revision red" */
--font-display: "IBM Plex Sans Condensed", sans-serif;
--font-sans: "IBM Plex Sans", sans-serif;
--font-mono: "IBM Plex Mono", monospace;
--radius: 0;
```
Derived (not brand colours): `tint #F3F3F1` (hovered/selected row), `parser #6B726D` (provenance: read from the design file), `on-ink #D6D9D5` (text on the sidebar). All text pairs pass WCAG 2.2 AA (4.5:1) on the sheet and on `tint`; the numbers are asserted in `apps/web/src/a11y.test.ts`.

**Colour rules**
- Violet and green mean **only** provenance of a decision and the variant (A = LLM only, B = hybrid). Never for buttons, links or statuses (`apps/web/src/design-rules.test.ts` enforces where the tokens may appear).
- The primary action is black (`ink`): a filled button; secondary actions have a 1px outline.
- Status is always icon + text: compliant in `ink` with a check mark, "to check" in `status-warn`, "needs a decision" in `status-error`.

**Typography:** IBM Plex Sans Condensed 600 for page and panel titles (like lettering on a drawing), sentence case, never upper case; IBM Plex Sans for all body text; IBM Plex Mono only for **data** (MPN, designators, footprints, token/time/cost counters, run numbers), not for labels. Fonts are served locally (`@fontsource`, subsets `latin` and `latin-ext`, so Polish diacritics render); a test sets "Zażółć gęślą jaźń".

**Three signature elements**
1. **Provenance rail.** Every BOM row has an 8px rail on its left. LLM agent: hatched at 135 degrees (3px violet, 3px white). Rule: solid green. Design file: solid grey. Person: solid black. Pattern *and* colour, so provenance survives black-and-white print and colour-vision deficiency. The selected row has a 2px `ink` outline. The item panel has the same rail next to its title.
2. **Title block.** On document screens (BOM, comparison) a 3x3 grid with a 1px outline: project name, revision (BOM version as a letter), run number, date, variant, sheet number, status. Data comes from the real run; on a demo deployment the status cell reads "Illustrative". It is the only place where run metadata is shown. On narrow screens it sits under the table.
3. **Run path.** The stages of a run are joined by 3px segments bent at 45 degrees; nodes are square vias (16px, 3px outline); the last node is filled when the run is complete. The colour of a segment says who performed the stage (violet LLM, green rule, grey parser, black person). One SVG component (`RunPath`) with `role="img"` and a text description. For "Both variants" two paths sit side by side in frames carrying the provenance rail of their variant.

The **zone frame** (numbers 1-6 along the top edge of the sheet) is used only on the brand/sign-in screen and in the PDF export of the BOM, never on everyday screens.

**Motion:** exactly one animation in the product. When a run stage finishes (SSE event), its path segment draws in over 240ms. With `prefers-reduced-motion` it appears immediately. No other transitions, spinners or pulses.

**Without:** ALL-CAPS labels above headings, "→" arrows in buttons, numbered markers where the content is not a sequence, decorative gradients, shadows, rounded corners, a dark theme, identical cards with an identical shadow. Empty states always carry an action, never a bare "0".

**Illustrative numbers:** numbers on demo deployments are marked "Illustrative data" (`Dane poglądowe`); nothing on a screen or in a mock-up is a research result.

## 4. Screens (v1 minimum)
1. **Start** (as above).
2. **Projects** – list + upload (drag & drop of a folder, format detection, a message about format limitations).
3. **New run** – modal (as above).
4. **Live run** – the run path (section 3) drawing in as stages finish, time/token/cost counters in Plex Mono, SSE; for the "Both" mode – two paths in framed columns.
5. **BOM** – table (TanStack Table) on a sheet: provenance rail on the left of the row, joined filter buttons ("only with remarks", "LLM decisions", "rule decisions"), title block; item **side panel**: justification, citation from the knowledge base (underlined in `cite`, with a link to the document and page), the result of each rule, change history, "Change".
6. **Variant comparison** – frames A and B with their run paths, below them metrics vs the reference BOM (columns A and B in the provenance colours, values in Plex Mono), per-item differences, title block.
7. **Knowledge base** – the organization's documents + an overview of the global corpus (read-only), indexing status.
8. **Audit log** – filtering by user, object, time; export.
9. **Organization settings** – members and roles, SSO (SAML/OIDC), API keys, limits and usage, data retention.
10. **Onboarding** – organization registration, domain verification, first project from a template.

## 5. Copy (UX writing)
Sentences written in plain language, from the user's perspective; the button says what will happen ("Run" – "Uruchom przebieg", "Export CSV" – "Eksportuj CSV"), the toast uses the same verb ("CSV exported" – "Wyeksportowano CSV"). Errors say what happened and how to fix it ("The .brd file is not supported directly. Export IPC-2581 from Allegro and upload it here." – "Plik .brd nie jest obsługiwany bezpośrednio. Wyeksportuj IPC-2581 z Allegro i wgraj go tutaj."). An empty state = an invitation to act. PL and EN from the start (i18n).

## 6. Quality
WCAG 2.2 AA (contrast, visible focus, full keyboard support, `prefers-reduced-motion`), responsiveness down to 375 px (BOM table scrolls horizontally, side panel as a drawer, the title block under the table), loading states (skeletons), error and empty states for every list. Every screen: a Playwright screenshot in the PR + an axe test.
