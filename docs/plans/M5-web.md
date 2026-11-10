# M5 – frontend (część 1)

Gałąź `feat/m5-web` (na `feat/m4-runs-api`).

## Zakres zrobiony
1. API: `GET /v1/projects/{id}/designs` (lista wersji projektu, 404 dla obcego tenanta); baza wiedzy organizacji: `POST /v1/kb/documents` (metadane + SHA-256, presigned PUT pod prefiksem tenanta, duplikat → 200 bez uploadu), `POST /v1/kb/documents/{id}/complete` (kolejka kb-indexer), `GET /v1/kb/documents[/{id}]` (dokumenty organizacji + wspólny korpus); kontrakt OpenAPI zaktualizowany, test izolacji. Przegląd BOM przez człowieka: `PATCH /v1/runs/{id}/bom/items/{line}` (migracja 0004: kopia „po przeglądzie”, oryginał agentów nietknięty, `?version=original`), proweniencja `user` z uzasadnieniem, ponowna walidacja regułami, audyt before/after, opcja „zapamiętaj” → korekta w bazie wiedzy tylko tej organizacji (kb-indexer `kb.correction.requested`).
2. `apps/web`: shell (sidebar z przełącznikiem organizacji, topbar), Start (powitanie, szablony, liczniki, przewodniki), Projekty + szczegóły z uploadem, Nowy przebieg (Radix Dialog, RHF, A/B/A+B), Przebieg na żywo (kroki jako pasek potoku, zużycie, BOM z paskiem pochodzenia, filtr „tylko z uwagami”, eksport CSV z ochroną przed CSV injection, panel pochodzenia z cytatami KB), Porównanie A vs B (metryki liczone z BOM i śladów, oznaczenie danych z symulatora), Baza wiedzy (lista + dodawanie dokumentu, hash liczony w przeglądarce), poprawianie pozycji BOM w panelu pozycji (znacznik „Po przeglądzie”), Log audytu, Powiadomienia, Ustawienia (język PL/EN).
3. Testy: vitest (12), Playwright 21 (13 desktop + 8 mobile smoke) z axe – 0 poważnych naruszeń; API: KB 5 + przegląd BOM 4 testy integracyjne (w tym izolacja). Całość Pythona: 350 testów, pokrycie 94%.
4. Zrzuty ekranów: `docs/design/screens/m5/`.

## Do zrobienia (M5 część 2)
- Logowanie OIDC (PKCE) i wybór organizacji z tokenu; onboarding nowej organizacji.
- Baza wiedzy: usuwanie/zastępowanie wersji dokumentu, podgląd fragmentów i flag prompt injection; przegląd BOM: zatwierdzenie całego BOM, eksport wersji po przeglądzie, porównanie oryginał ↔ przegląd.
- Ustawienia: członkowie i role, SSO, klucze API, limity (zależne od M4 część 2).
- Tłumaczenie komunikatów reguł po `rule_id`; podział bundla.
- E2E na pełnym stosie (`E2E_BASE_URL`) w CI z dockerem.
