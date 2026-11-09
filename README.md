# mgr-ibm · BOM Agent

**Praca magisterska (PG WETI, Inżynieria Biomedyczna):** Porównanie systemu wieloagentowego opartego na dużych modelach językowych z systemem wieloagentowym z elementami deterministycznymi w zastosowaniu do generowania BOM urządzeń biomedycznych.

Bartosz Malinowski · opiekun: dr inż. Magdalena Mazur-Milecka

Repozytorium jest jednocześnie **stanowiskiem badawczym** i **produkcyjną platformą SaaS** (multi-tenant, UE, SSO), która z plików CAD/EDA, PDF i DXF/DWG generuje i waliduje BOM przy pomocy agentów LLM.

## Start
| Chcę… | Plik |
|---|---|
| zbudować aplikację przez Claude Code | [`docs/prompts/CLAUDE_CODE_MASTER_PROMPT.md`](docs/prompts/CLAUDE_CODE_MASTER_PROMPT.md) |
| zrozumieć architekturę produkcyjną | [`docs/platform/ARCHITECTURE.md`](docs/platform/ARCHITECTURE.md), [`docs/adr/`](docs/adr/README.md) |
| zobaczyć, co już działa | [`docs/STATUS.md`](docs/STATUS.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| pisać pracę | [`thesis/Praca_magisterska_Bartosz_Malinowski_szablon.docx`](thesis/), [`docs/thesis/STRUKTURA_PRACY.md`](docs/thesis/STRUKTURA_PRACY.md) |
| zobaczyć warianty A i B | [`docs/thesis/ARCHITEKTURA_WARIANTOW.md`](docs/thesis/ARCHITEKTURA_WARIANTOW.md) |
| projektować UI | [`docs/design/UX_GUIDELINES.md`](docs/design/UX_GUIDELINES.md) |

## Mapa repozytorium
```
CLAUDE.md                 zasady dla Claude Code (czytane w każdej sesji)
docs/platform/            architektura, bezpieczeństwo, testy, formaty
docs/adr/                 decyzje architektoniczne (15)
docs/design/              wytyczne UX, inspiracje (Mobbin), prototyp v0
docs/prompts/             prompt startowy dla Claude Code
docs/thesis/              materiały do pracy magisterskiej
docs/img/                 diagramy
thesis/                   szablon pracy (DOCX)
tools/                    generatory diagramu i szablonu DOCX
```
Kod aplikacji (`apps/`, `services/`, `packages/`, `infra/`, `deploy/`, `evals/`) powstaje zgodnie z [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Regeneracja materiałów do pracy
```bash
python3 tools/arch.py docs/img/architektura.svg && rsvg-convert -z 2 docs/img/architektura.svg -o docs/img/architektura.png
node tools/build_docx.js . thesis/Praca_magisterska_Bartosz_Malinowski_szablon.docx
```
