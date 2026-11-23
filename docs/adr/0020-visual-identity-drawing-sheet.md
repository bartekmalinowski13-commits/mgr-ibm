# ADR-0020: Visual identity - the technical drawing sheet

Status: Accepted · 2026-11-23

## Context
The first UI used soft tokens (radii of 8-18px, a dialog shadow, a heavy display typeface, violet and green
also on pills and buttons). Two things have to be readable on every screen: **where a decision came from**
(an LLM agent or a rule) and **how variant A differs from variant B**. The audience (electronics and
quality engineers, the thesis committee) reads BOM documents that are checked and signed; the product
should look like one. A canvas with three artboards (brand, BOM, run and comparison) fixes the direction.

## Decision
- Visual language: a **technical drawing sheet**: radius 0, 1px `ink` outlines, dense tables, lines instead
  of shadowed cards, white sheet on a grey desk on document screens, black sidebar. No shadows, no
  gradients except the hatched LLM rail, no dark theme. Tokens and rules: `docs/design/UX_GUIDELINES.md` §3.
- **Colour has one meaning each.** Violet = LLM agent decision / variant A; green = rule decision /
  variant B; both never on buttons, links or statuses. Primary action = `ink`. Status = icon + text.
- **Provenance is double-coded** (pattern + colour): hatched rail = LLM, solid green = rule, solid grey =
  parser, solid ink = person. Rationale: black-and-white print, colour-vision deficiency (WCAG 1.4.1).
- **Typography:** IBM Plex Sans Condensed 600 (titles), IBM Plex Sans (text), IBM Plex Mono (data only),
  self-hosted via `@fontsource`, subsets `latin` + `latin-ext`. Replaces Bricolage Grotesque.
- **Three signature components** in `packages/ts/ui`: `ProvenanceRail`, `TitleBlock`, `RunPath`. The
  title block is the only place with run metadata; the run path is one accessible SVG.
- **One animation:** a finished stage draws its path segment in 240ms; `prefers-reduced-motion` = instant.
- Guard rails are tests, not review comments: `apps/web/src/design-rules.test.ts` fails on rounded
  corners, shadows, gradients, extra animations, the old fonts and violet/green outside provenance code;
  `a11y.test.ts` asserts the contrast of every token pair.
- shadcn/ui stays the component base (ADR-0014): components are copied into `packages/ts/ui` and bound to
  these tokens. The `--radius-*`/`--shadow-*` theme scales are cleared, so such utilities do not exist.

## Consequences
- The identity is deliberately the opposite of the author's other application; nothing is shared with it.
- Colour-only or shape-only cues are not used; every status and provenance mark carries text or pattern.
- Changing a token or relaxing a rule means a new ADR and an edit of the two tests above.
- A black sidebar needs its own focus ring (white); handled by the `on-ink` class.

## Alternatives considered
- Keep the soft identity and only recolour: does not make provenance readable in print.
- A dark theme with an accent: rejected (neon-on-black is the opposite of an engineering document).
- Violet/green as status colours: rejected, it blurs "who decided" with "is it correct".
