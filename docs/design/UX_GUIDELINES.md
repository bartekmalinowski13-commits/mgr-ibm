# UX/UI guidelines

Sources: the UX designer's recommendations (Mobbin + the frontend-design skill + shadcn/ui), inspiration from **Homerun (web)** on Mobbin (`inspiration/mobbin-homerun-home-and-modal.png`), the earlier flow prototype (`prototype/v0-flow.html`).

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
| Large, heavy greeting "Hi there Sam" – typography as a graphic element | "Hello, Bartek" ("Cześć, Bartek") in a heavy display typeface; the only place on the screen with typography this large |
| "Create a new job" panel with a template carousel ("No template" card with a plus + cards with covers), closed with a cross | **"New BOM run"** panel (Nowy przebieg BOM): an "Empty project" card (+) (Pusty projekt) and templates of example devices (wearable ECG, pulse oximeter, EEG amplifier, infusion pump…) with **our own** covers (SVG illustrations themed on PCBs/sensors) |
| A row of stat cards that in the empty state are an invitation ("No active jobs", "No candidates", "1 to-do") | Cards: active runs, items to review, open validation remarks, projects – **empty states always with an action**, not an empty "0" number |
| "Guides" section with illustrated cards | "Guides" (Przewodniki): how to prepare a KiCad project, how variants A and B differ, the IEC 60601 checklist, how to export IPC-2581 from Altium/Allegro |
| "Create new job" modal: labels on the left, fields on the right, asterisk for required, selects, **radio cards with mini illustrations** ("Job post and application form" / "Only application form"), footer: Cancel + green Continue | **"New run"** modal (Nowy przebieg): Name*, Project (select / upload), Device requirements (application part, power supply), Model (closed / open-weight), **Variant as radio cards with a mini pipeline diagram** (A: 100% LLM / B: hybrid / Both + comparison); footer: Cancel (Anuluj) + Next (Dalej) |
| Warm, light background, white cards with a delicate border, large card rounding, few shadows | Light neutral background, white surfaces, 1px borders, radius depending on hierarchy (large cards > buttons > markers) |
| Purple accent (trial) and green (primary) | See the semantic colours below – we preserve the distinction of decision provenance |

## 3. Tokens (starting point – to be refined with the frontend-design skill)
**Semantic colours (constant across the whole product and in diagrams):**
- `provenance.llm` – purple (decision of an LLM agent)
- `provenance.rule` – solder-mask green (decision of a deterministic rule)
- `status.ok` / `status.warn` / `status.error` – green / amber / red, always with an icon and text (not colour alone)
- `action.primary` – dark ink (not green, so it is not confused with `provenance.rule`)
- background: a light, cool paper grey; surfaces: white; borders: 1px grey

**Typography:** a heavy display typeface for the greeting and page headings (proposal: Bricolage Grotesque 800, OFL licence); text typeface: IBM Plex Sans; technical data (MPN, designators, footprints): IBM Plex Mono. Type scale after "The Elements of Typographic Style", text line length < 80 characters.

**Without:** ALL-CAPS labels above every heading, "→" arrows in buttons, numbered markers where the content is not a sequence, decorative gradients, identical cards with an identical shadow.

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
