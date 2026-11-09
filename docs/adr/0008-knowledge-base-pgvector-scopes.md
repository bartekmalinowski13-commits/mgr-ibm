# ADR-0008: Baza wiedzy: pgvector, zakres globalny + przestrzenie per tenant

Status: Zaakceptowany · 2026-11-09

## Kontekst
Jedna wspólna baza wiedzy, ale organizacje nie mogą widzieć ani uczyć się z danych innych.

## Decyzja
pgvector + pełnotekstowe wyszukiwanie Postgresa (hybryda) + reranker. Kolumna `scope` (`global`|`tenant`), RLS: `tenant_id = current OR scope = 'global'`. Zapis do `global` tylko przez pipeline platformy. Poprawki użytkowników = wiedza tenanta. Snapshot KB zapisywany przy każdym przebiegu.

## Konsekwencje
Jedna baza danych do utrzymania, transakcyjna spójność z resztą danych, izolacja tym samym mechanizmem co reszta. Gdy wektory przekroczą ~50 mln – ADR o migracji (OpenSearch Serverless).

## Rozważane alternatywy
OpenSearch Serverless (osobny system, wyższy koszt minimalny); Pinecone (podprocesor spoza AWS).
