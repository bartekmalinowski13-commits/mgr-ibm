# M5 – Frontend (`apps/web`)

## Brainstorming (questions and answers from the documents)
| Question | Answer | Source |
|---|---|---|
| Stack | React + Vite + TanStack Router/Query/Table + Tailwind + shadcn-style components in `packages/ts/ui` | ADR-0014 |
| Local login | mock IdP in the API (`/v1/dev/token`); in the cloud Cognito Hosted UI + PKCE (M6) | ADR-0005, DECISIONS_LOG |
| Live progress | SSE via `fetch` (EventSource does not send the Authorization header) | ADR-0015 |
| Model list in the modal | new `GET /v1/models` – the same rule as the `POST /v1/runs` validation | model catalog (M2) |
| E2E without Docker | `tools/devstack.py`: API + workers in one process, a fresh database; in CI the compose stack | TESTING.md |

## Visual plan (frontend-design skill, review vs a "generic" pattern)
- **Palette:** paper `#ECEFF2` (cool grey, not cream), surfaces `#FFFFFF`, ink `#18212B` (primary action – not green, so it is not confused with a rule), lines `#D3D9DF`, LLM violet `#5B3FD6`, solder-mask green `#13704A`, amber `#A35A00`, red `#B42318`.
- **Typography:** Bricolage Grotesque 800 only in the greeting and titles; IBM Plex Sans in the interface; Plex Mono only for technical data (designators, MPNs, packages) – not for labels.
- **The one bold element:** a provenance bar (4 px) next to every BOM row in the colour of whoever decided (agent / rule / file / human), repeated in the "Kto zdecydował" ("Who decided") bar and in the pipeline sketches on the variant cards in the modal. The rest is calm: radii by hierarchy (panel 18 > card 12 > control 8), no UPPERCASE labels, no gradients, no arrows in buttons.
- **Changes after the review:** I dropped the large numbers in the stat cards in the empty state (instead of "0" – a call to action, as in UX_GUIDELINES), and the item panel is a drawer below 1536 px, because with the panel next to the table the MPN column was being cut off.

## v1 scope (done)
Login (local), onboarding (organization, joining with an invitation code), a shell with an organization switcher, Start (greeting, device templates with custom SVG illustrations, cards with empty states), Projects (list, creation, drag & drop upload, file statuses), the New run modal (project, variant A/B/both, model from the catalog, device requirements), Live run (SSE, counters), BOM (table, the "tylko z uwagami" ("only with remarks") filter, provenance panel, correction → new version + organization knowledge), CSV export, Audit log (filter, chain verification), Settings (members and roles, invitations, API keys with rotation, usage and limits, SSO – information), PL/EN.

Variant A/B comparison: run metrics (items, LLM calls, tokens, cost, remarks) and per-designator differences (value, manufacturer, MPN) with the provenance colour.

Evaluation against the reference BOM: the user uploads a CSV (≤ 1 MB, not stored), the API computes the metrics with `bomagent_eval` (the same as in the experiment), audit event `bom.evaluated`.

Knowledge base: organization documents (upload PDF/MD/TXT → S3 → outbox → kb-indexer, statuses, number of chunks) and a read-only global corpus.

## To do in M5 (next steps)
a run step timeline with the step kind (requires step events in SSE), Cognito login (PKCE) together with M6, screenshots in the PR.
