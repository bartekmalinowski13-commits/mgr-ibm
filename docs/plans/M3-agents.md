# M3 – Agenci, warianty A i B (plan)

Źródła: ROADMAP M3, ADR-0006, ADR-0007, ARCHITEKTURA_WARIANTOW.md, SECURITY.md.

## Brainstorming – pytania i odpowiedzi
| Pytanie | Decyzja | Uzasadnienie |
|---|---|---|
| Jak zapewnić porównywalność A i B? | ten sam retriever, model, prompt doboru MPN i zasada „MPN tylko z dowodów” | różnice przypisywalne architekturze |
| Co robi LLM w B? | tylko dobór MPN dla pozycji bez MPN + naprawa po błędach reguł | ARCHITEKTURA_WARIANTOW (tabela kroków) |
| Co robi kod w A? | wyłącznie konwersja JSON → `BomItem` (bez grupowania/ilości) | „100 % LLM” |
| Fan-out i współbieżność | LangGraph `Send` + `max_concurrency` z `RunConfig` | R7 (szybkość) |
| Structured output | JSON Schema w `response_format`, walidacja Pydantic, 1 ponowienie | R7, brak pętli parsowania |
| Checkpointy | pamięć; Postgres po zaprojektowaniu tabel z RLS | izolacja tenantów > wygoda |
| Claude Agent SDK | adapter z narzędziami MCP w procesie, bez narzędzi wbudowanych | ADR-0007, SECURITY.md |

## Zadania – stan
1. `llm.chat` (gateway + fake + kasety) – ✅
2. prompty wersjonowane, kontrakt `VariantRuntime`, budżety, retrievery – ✅
3. `langgraph_b`, `langgraph_a`, `claude_agent_sdk_a` – ✅
4. `fake_server` (compose), CLI `bomagent run`, `agent-worker` – ✅

## Kryteria akceptacji
Przebieg A i B na fixture KiCad z fałszywym LLM daje BOM (testy `packages/py/agents`, `services/agent-worker`); ślad kroków: `RunOutput.trace` + spany OTel `node *` i `chat *` (atrybuty `gen_ai.*`); CLI `bomagent run --variant A|B` działa. Ślad w Langfuse – przez callback OTel w LiteLLM (compose), niezweryfikowany lokalnie (brak Dockera).
