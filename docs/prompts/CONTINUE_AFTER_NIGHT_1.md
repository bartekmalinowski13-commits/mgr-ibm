# Kontynuacja po pierwszej nocy (10.11.2026)

Stan: kod jest na czterech gałęziach ułożonych jedna na drugiej (każda bazuje na poprzedniej):

1. `claude/code-master-prompt-part-2-5651f9` – M0–M2 (sesja Claude Code)
2. `feat/m3-agents-runtimes` – M3, agenci A/B
3. `feat/m4-runs-api` – M4 część 1, przebiegi przez API
4. `feat/m5-web` – M5 część 1 (UI) + z M4 części 2: API bazy wiedzy i przegląd BOM przez człowieka

Szczegóły: `docs/STATUS.md`, założenia do akceptacji: `docs/DECISIONS_LOG.md`.

## Jak scalić (człowiek)

Najprościej: jeden PR z `feat/m5-web` do `main` (zawiera wszystkie cztery etapy), squash albo merge commit.
Jeśli wolisz review etapami: PR-y kolejno 1 → `main`, 2 → `main` (po scaleniu 1), itd.
Pierwsze CI na PR uruchomi ścieżkę z Dockerem (Testcontainers, `just up`, E2E na stosie), której nie dało się sprawdzić w nocy.

## Prompt do wklejenia w Claude Code (po scaleniu do `main`)

```
Przeczytaj CLAUDE.md, docs/STATUS.md, docs/DECISIONS_LOG.md, docs/plans/M4-runs-api.md
i docs/plans/M5-web.md. Pracuj według ROADMAP i superpowers (plan → TDD → review →
weryfikacja). Kolejność:

1. Jeśli CI na main jest czerwone – najpierw napraw (systematic-debugging), osobny PR fix/….
2. M4 część 2: onboarding organizacji (zaproszenia, role), SSO per organizacja (OIDC/SAML
   przez Cognito), klucze API organizacji (hash, zakresy, rotacja), metering i limity,
   checkpointy LangGraph w Postgresie, wygenerowany klient TS (packages/ts/api-client).
3. M5 część 2: logowanie OIDC w UI (PKCE, tokeny w pamięci), onboarding, ustawienia
   (członkowie, SSO, klucze API, limity), zatwierdzenie całego BOM i eksport wersji po
   przeglądzie, porównanie oryginał ↔ przegląd, tłumaczenie szczegółów komunikatów reguł (parametry w Finding).
4. M6: CDK + cdk-nag (bez wdrażania), CORS bucketu dla uploadu z przeglądarki.

Jedna gałąź feat/… na zadanie, PR do main. Po każdym kamieniu: STATUS.md, DECISIONS_LOG.md.
Nie zmieniaj ADR-ów po cichu. Nie wdrażaj do AWS. Nie używaj prawdziwych kluczy LLM w testach.
```

## Demo interfejsu bez backendu

`pnpm --filter @bomagent/web dev:mock` – dane przykładowe z prawdziwych przebiegów symulatora (to nie są wyniki badań).
