# ui (`@bomagent/ui`)

Component base of the web app in the shadcn/ui style (ADR-0014): Radix primitives,
Tailwind classes against the design tokens defined in `apps/web/src/styles.css`.

- **Public interface:** `Button`, `Dialog`/`DialogContent`/`DialogFooter`, `Field` (label
  left, control right), `Input`, `Select`, `Textarea`, `StatusBadge` (icon + text, never
  colour alone), `Menu`, `cn`.
- **Test:** `pnpm --filter @bomagent/ui typecheck lint`; behaviour and accessibility are
  covered by the web app's Playwright + axe scenarios.
