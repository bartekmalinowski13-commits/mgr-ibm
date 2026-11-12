# mgr-ibm · BOM Agent

**Master's thesis (Gdańsk University of Technology, Faculty of Electronics, Telecommunications and Informatics (PG WETI), Biomedical Engineering):** Comparison of a multi-agent system based on large language models with a multi-agent system with deterministic elements, applied to generating the BOM of biomedical devices.

Bartosz Malinowski · supervisor: dr inż. Magdalena Mazur-Milecka

The repository is both a **research testbed** and a **production SaaS platform** (multi-tenant, EU, SSO) that generates and validates a BOM from CAD/EDA, PDF and DXF/DWG files with the help of LLM agents.

## Start
| I want to… | File |
|---|---|
| build the application with Claude Code | [`docs/prompts/CLAUDE_CODE_MASTER_PROMPT.md`](docs/prompts/CLAUDE_CODE_MASTER_PROMPT.md) |
| understand the production architecture | [`docs/platform/ARCHITECTURE.md`](docs/platform/ARCHITECTURE.md), [`docs/adr/`](docs/adr/README.md) |
| see what already works | [`docs/STATUS.md`](docs/STATUS.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| write the thesis | [`thesis/Praca_magisterska_Bartosz_Malinowski_szablon.docx`](thesis/), [`docs/thesis/STRUKTURA_PRACY.md`](docs/thesis/STRUKTURA_PRACY.md) |
| see variants A and B | [`docs/thesis/ARCHITEKTURA_WARIANTOW.md`](docs/thesis/ARCHITEKTURA_WARIANTOW.md) |
| design the UI | [`docs/design/UX_GUIDELINES.md`](docs/design/UX_GUIDELINES.md) |

## Repository map
```
CLAUDE.md                 rules for Claude Code (read in every session)
docs/platform/            architecture, security, tests, formats
docs/adr/                 architecture decisions (15)
docs/design/              UX guidelines, inspirations (Mobbin), prototype v0
docs/prompts/             starting prompt for Claude Code
docs/thesis/              materials for the master's thesis
docs/img/                 diagrams
thesis/                   thesis template (DOCX)
tools/                    generators of the diagram and the DOCX template
```
The application code (`apps/`, `services/`, `packages/`, `infra/`, `deploy/`, `evals/`) is created according to [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Regenerating the thesis materials
```bash
python3 tools/arch.py docs/img/architektura.svg && rsvg-convert -z 2 docs/img/architektura.svg -o docs/img/architektura.png
node tools/build_docx.js . thesis/Praca_magisterska_Bartosz_Malinowski_szablon.docx
```
