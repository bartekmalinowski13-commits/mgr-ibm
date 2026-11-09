# ADR-0007: Runtime agentów: LangGraph + adapter Claude Agent SDK

Status: Zaakceptowany · 2026-11-09

## Kontekst
Dwa warianty systemu do porównania; potrzebny pełny ślad kroków, wznawianie i szybkość.

## Decyzja
Interfejs `VariantRuntime`. Implementacje: `langgraph_a` (100% LLM), `langgraph_b` (hybryda), `claude_agent_sdk_a` (wariant A na gotowej pętli agentowej). Checkpointy LangGraph w Postgresie. Równoległy fan-out pozycji, tiering modeli, structured output, budżety czasu/tokenów.

## Konsekwencje
Uczciwe porównanie: ten sam kontrakt wejścia/wyjścia i te same biblioteki domenowe. Koszt: utrzymanie dwóch frameworków – Claude Agent SDK tylko w jednym adapterze.

## Rozważane alternatywy
CrewAI/AutoGen (mniej kontroli nad stanem); własny orkiestrator (więcej kodu do utrzymania).
