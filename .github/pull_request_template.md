## What and why

<!-- one paragraph; link the ROADMAP milestone and ADRs this touches -->

## How it was tested

- [ ] tests written before code (TDD) and green locally (`just test`)
- [ ] `just lint` clean (ruff, mypy --strict, import-linter, biome)
- [ ] tenant isolation suite green (`just test-isolation`) - required for data changes
- [ ] screenshots (UI changes) + axe clean

## Definition of Done (CLAUDE.md)

- [ ] module README updated
- [ ] OTel spans on new paths
- [ ] audit event for every data-changing operation
- [ ] RLS policies reviewed (if migration touches tenant tables)
- [ ] `docs/STATUS.md` updated (milestone PRs)
- [ ] no secrets, no non-EU endpoints
