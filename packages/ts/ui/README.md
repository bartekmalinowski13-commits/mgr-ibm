# ui (`@bomagent/ui`)

Component base of the web app in the shadcn/ui style (ADR-0014): Radix primitives,
Tailwind classes against the design tokens defined in `apps/web/src/styles.css`.
Visual direction: "fabrication drawing" (ADR-0019, `docs/design/UX_GUIDELINES.md` §2–3).

- **Public interface:** `Button`, `Dialog`/`DialogContent`/`DialogFooter`, `SheetContent` (left drawer, e.g. mobile
  navigation, with focus trap and Escape), `Field` (label
  left, control right), `Input`, `Select`, `Textarea`, `StatusBadge` (icon + text, never
  colour alone), `Menu`, `cn`, `buttonClass` (button look for links).
- **Fabrication drawing (ADR-0019):** `Sheet` + `SheetHeader` (sheet with the A–H / 1–6 zone frame,
  dropped below 900 px; `SHEET_ZONES`), `TitleBlock` (name, sheet number, up to 6 cells),
  `MaskPanel` + `Silk` (the board panel, at most one per screen), `ProvenanceGlyph`,
  `ProvenanceLegend`, `PROVENANCE_STRIPE` (agent = hollow circle, rule = square, parser =
  diamond, person = disc), `VariantChip` (A violet / B green), `ViaTimeline` (run steps as vias
  on copper tracks; the only animation, off under reduced motion).
- **Test:** `pnpm --filter @bomagent/ui typecheck lint`; behaviour and accessibility are
  covered by the web app's Playwright + axe scenarios (`apps/web/e2e/visual.spec.ts` renders every
  component on the preview page `/design`).
