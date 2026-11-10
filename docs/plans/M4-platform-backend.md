# M4 – Platforma SaaS: backend (plan i stan)

Źródła: ROADMAP M4, ADR-0004/0005/0011/0015, SECURITY.md, TESTING.md.

## Brainstorming – pytania i odpowiedzi
| Pytanie | Decyzja | Uzasadnienie |
|---|---|---|
| Skąd role użytkownika? | z bazy (`tenancy.memberships`), nie z tokenu | rola zmienia się bez ponownego logowania; token IdP nie zna organizacji BOM Agent |
| Jak znaleźć organizacje użytkownika przy logowaniu bez obejścia RLS? | `app.user_sub` + polityki `member_self`/`member_tenants` (tylko SELECT własnych członkostw) | brak ról z BYPASSRLS (CLAUDE.md) |
| Kto tworzy tenanta? | rola `bomagent_platform` (onboarding), audyt w nowym tenancie | rola aplikacji nie może tworzyć tenantów |
| Lokalny IdP | mock RS256 z efemerycznym kluczem, tylko local/test | ADR-0005: aplikacja zależy wyłącznie od OIDC |
| Edycja BOM | nowa niemutowalna wersja + pochodzenie `user` + korekta MPN jako wiedza tenanta | ISO 13485 identyfikowalność, ADR-0008 |
| Parsowanie wgranych plików | wyłącznie w ingest-worker (sandbox), API tylko zapisuje i kolejkuje | ADR-0009 |

## Stan
1. Migracja 0003 + testy izolacji – ✅
2. API: auth/RBAC/organizacje/projekty/upload/przebiegi/SSE/BOM/edycja/eksport/audyt, OpenAPI 3.1, kontrakt (Schemathesis) – ✅
3. Workery zapisują do bazy (status przebiegu, wersje BOM, wynik parsowania) – ✅
4. Klient TS z OpenAPI – kolejny krok
5. Do zrobienia później: zaproszenia członków, klucze API organizacji, limity/metering, konfiguracja SSO per organizacja (formularz → Cognito), rate limiting.

## Kryteria akceptacji
Testy kontraktowe, integracyjne i izolacji zielone; zdarzenie audytowe dla każdej mutacji (sprawdzane w `test_api_flow`).
