# M5 – frontend (część 1)

Gałąź `feat/m5-web` (na `feat/m4-runs-api`).

## Zakres zrobiony
1. API: `GET /v1/projects/{id}/designs` (lista wersji projektu, 404 dla obcego tenanta); baza wiedzy organizacji: `POST /v1/kb/documents` (metadane + SHA-256, presigned PUT pod prefiksem tenanta, duplikat → 200 bez uploadu), `POST /v1/kb/documents/{id}/complete` (kolejka kb-indexer), `GET /v1/kb/documents[/{id}]` (dokumenty organizacji + wspólny korpus); kontrakt OpenAPI zaktualizowany, test izolacji.
2. `apps/web`: shell (sidebar z przełącznikiem organizacji, topbar), Start (powitanie, szablony, liczniki, przewodniki), Projekty + szczegóły z uploadem, Nowy przebieg (Radix Dialog, RHF, A/B/A+B), Przebieg na żywo (kroki jako pasek potoku, zużycie, BOM z paskiem pochodzenia, filtr „tylko z uwagami”, eksport CSV z ochroną przed CSV injection, panel pochodzenia z cytatami KB), Porównanie A vs B (metryki liczone z BOM i śladów, oznaczenie danych z symulatora), Baza wiedzy (lista + dodawanie dokumentu, hash liczony w przeglądarce), Log audytu, Powiadomienia, Ustawienia (język PL/EN).
3. Testy: vitest (11), Playwright 21 (13 desktop + 8 mobile smoke) z axe – 0 poważnych naruszeń; API KB: 5 testów integracyjnych (w tym izolacja).
4. Zrzuty ekranów: `docs/design/screens/m5/`.

## Do zrobienia (M5 część 2)
- Logowanie OIDC (PKCE) i wybór organizacji z tokenu; onboarding nowej organizacji.
- Baza wiedzy: usuwanie/zastępowanie wersji dokumentu, podgląd fragmentów i flag prompt injection; edycja pozycji BOM przez człowieka (`provenance=user`).
- Ustawienia: członkowie i role, SSO, klucze API, limity (zależne od M4 część 2).
- Tłumaczenie komunikatów reguł po `rule_id`; podział bundla.
- E2E na pełnym stosie (`E2E_BASE_URL`) w CI z dockerem.
