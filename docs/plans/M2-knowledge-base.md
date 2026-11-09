# M2 – Baza wiedzy (plan)

Źródła: ROADMAP M2, ADR-0006, ADR-0008, SECURITY.md (prompt injection), TESTING.md.

## Brainstorming – pytania i odpowiedzi
| Pytanie | Decyzja | Uzasadnienie |
|---|---|---|
| Wymiar wektorów | `vector(1024)` | Titan Text Embeddings V2 i Cohere Embed v3 (Bedrock) dają 1024; indeks HNSW wymaga stałego wymiaru |
| Jak zapewnić powtarzalność (`kb_snapshot_id`)? | dokumenty niemutowalne (`supersedes`), snapshot = lista id aktywnych dokumentów | eksperyment da się odtworzyć dopóki dokumentów nie skasowano |
| Kto pisze do korpusu globalnego? | tylko rola `bomagent_platform` (polityka RLS), wiadomości tylko od pseudo-tenanta platformy | ADR-0008 |
| Docling – zależność obowiązkowa? | opcjonalna (obraz kb-indexer), testy na pypdf | Docling ciągnie torch (GB); PyMuPDF odrzucony (AGPL) |
| Reranker | leksykalny (deterministyczny), interfejs pod reranker z gateway | bez sieci w CI; ten sam kontrakt dla rerankera modelowego |
| Fałszywe embeddingi | haszowanie cech (słowa + trigramy) | deterministyczne testy retrieval bez modelu |
| Prompt injection w datasheetach | sanityzacja + flaga `injection_suspect`, takie fragmenty na końcu rankingu | SECURITY.md |
| Katalog MPN | `kb.parts` z ekstrakcji (sekcje „Ordering information”) + korekty użytkowników | podstawa metryki halucynacji MPN |

## Zadania (TDD) – stan
1. `llm`: katalog modeli (EU, closed/open-weight, weryfikacja przed włączeniem), embeddingi gateway/hashing – ✅
2. Migracja 0002 (`kb.documents/chunks/parts/snapshots`, RLS global/tenant, trigger właściciela dokumentu) – ✅
3. `kb`: ekstrakcja, chunking, części, bezpieczeństwo, store + retrieval hybrydowy + RRF + reranker, snapshoty, korekty – ✅
4. `kb-indexer`: handler SQS (tenant/global), wiring z ustawień – ✅
5. Fixture'y: 18 syntetycznych datasheetów (CC0) + zestaw 18 zapytań – ✅

## Kryteria akceptacji
Testy retrieval: recall@5 = 1,00, recall@1 = 0,89 (≥ 0,9 / ≥ 0,6 wymagane w teście). Testy izolacji KB (`tests/isolation/test_kb_isolation.py`) zielone.
