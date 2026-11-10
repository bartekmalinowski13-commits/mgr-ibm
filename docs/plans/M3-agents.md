# M3 – Agenci, warianty A i B (plan i realizacja)

Realizacja: Claude (projekt claude.ai „MGR - IBM”) podczas nocnego przeglądu 2026-11-10, gdy sesja Claude Code zatrzymała się po M2. Gałąź `feat/m3-agents-runtimes`, zbudowana na `claude/code-master-prompt-part-2-5651f9` (M0–M2).

Źródła: ROADMAP M3, ADR-0006, ADR-0007, ADR-0008, SECURITY.md (prompt injection), TESTING.md.

## Brainstorming – pytania i odpowiedzi
| Pytanie | Decyzja | Uzasadnienie |
|---|---|---|
| Wspólny kontrakt wariantów | `VariantRuntime.run(design, requirements, config, deps) -> RunResult` (BomVersion + trace + usage + config + model) | ADR-0007; to samo wejście/wyjście = uczciwe porównanie |
| Co jest wspólne dla A i B? | agent doboru części (`select_part@1.0.0`), baza wiedzy, model, schemat BOM | różnice w wynikach wynikają z architektury, nie z innych klocków |
| Wariant A – jak „100% LLM”? | orkiestrator → ekstrakcja (pętla narzędzi CAD) → grupowanie → dobór → walidacja (LLM) ⟲ ponowny dobór → kompozycja; deterministyczne są tylko narzędzia odczytu i mapowanie JSON → schemat | zgodnie z diagramem wariantów; naruszenia schematu nie są „cicho naprawiane”, tylko raportowane (`schema.coerced`) |
| Wariant B – gdzie LLM? | tylko dobór części dla pozycji bez MPN oraz naprawa pozycji odrzuconych przez reguły (max N iteracji) | ADR-0007 |
| Walidacja w B | pakiet `core@1.0.0` + reguła `kb.mpn_known` (MPN wybrany przez LLM musi być w katalogu KB tenanta/globalnym) | podstawa metryki halucynacji; reguła działa w warstwie agentów, bo potrzebuje KB |
| Fan-out | `asyncio.Semaphore(concurrency)` wewnątrz węzła, retrieval jednym wywołaniem `search_many` | prostsze i deterministyczne; `Send` LangGraph niepotrzebny przy równoległości per pozycja |
| Checkpointy LangGraph | parametr `checkpointer` (domyślnie brak); Postgres checkpointer w M4 razem z tabelą przebiegów | patrz DECISIONS_LOG |
| Structured output | JSON Schema w `response_format`, walidacja Pydantic, 1 ponowienie z błędem walidacji | mniej powtórek, mierzalne błędy formatu |
| Budżety | limity wywołań LLM, tokenów, czasu, iteracji naprawy i rund narzędzi; przekroczenie = przebieg `failed` z pełnym śladem | ARCHITECTURE §9 |
| Prompt injection | instrukcje tylko w komunikacie systemowym, dane w `<data>`/`<excerpt>` jako niezaufane; fragmenty KB oznaczone jako podejrzane nie trafiają do agentów | SECURITY.md |
| Fałszywy model | `FakeChat`: kasety (hash żądania) → symulator per prompt → błąd; ten sam mechanizm w serwerze `fake-llm` za LiteLLM | TESTING.md: deterministyczne CI |
| Claude Agent SDK | adapter `A-sdk` (jeden agent z narzędziami CAD + `search_kb`) za tym samym kontraktem; uruchamia się tylko z Bedrock w regionie UE | ADR-0006/0007; API SDK izolowane w jednej klasie |

## Zadania (TDD) – stan
1. `llm.chat`: model żądań/odpowiedzi, `GatewayChat` (OpenAI-compatible, OTel `gen_ai.*`) – ✅
2. `llm.fake` + `llm.fake_server` (kasety, symulatory, `/v1/chat/completions`, `/v1/embeddings`) – ✅
3. `agents`: prompty wersjonowane, schematy wyjść, `AgentLLM` (koszt, budżet, retry), narzędzia CAD, retrieval (KB z RLS / statyczny) – ✅
4. Runtime’y `A`, `B`, `A-sdk` + rejestr – ✅
5. Symulatory per prompt – ✅
6. `agent-worker`: handler `run.requested` (projekt z prefiksu tenanta, wynik `bom.json` + `result.json`) – ✅
7. CLI: `bomagent run`, `bomagent compare` (offline z symulatorem lub przez gateway) – ✅
8. Testy izolacji: `KbRetriever` nie widzi danych innego tenanta – ✅

## Kryteria akceptacji (ROADMAP M3)
- przebieg A i B na fixture’ach KiCad z fałszywym LLM daje BOM: ✅ (designator F1 = 1,0; line F1 ≥ 0,95; halucynacje 0)
- ślad kroków (TraceStep + spany OTel `agents.*`, `chat <model>`): ✅
- CLI `bomagent run --variant A|B`: ✅
- 330 testów, pokrycie 96%, ruff/mypy --strict/import-linter czyste.

**Uwaga:** wyniki z symulatora to test „hydrauliki”, nie dane badawcze. Eksperymenty do pracy (M8) idą na prawdziwych modelach przez gateway.
