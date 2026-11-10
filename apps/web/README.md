# apps/web – interfejs BOM Agent (M5)

React 19 + Vite 8, TanStack Router/Query, Tailwind CSS v4, Radix UI (dialog, dropdown, radio), react-hook-form, i18next (PL domyślnie, EN). Zasady wyglądu: `docs/design/UX_GUIDELINES.md`.

## Odpowiedzialność
Ekrany produktu: Start, Projekty (upload plików), okno Nowy przebieg (A / B / A + B), Przebieg na żywo z krokami i BOM (kolor = kto zdecydował: fiolet agent LLM, zieleń reguła, szary projekt), panel pochodzenia pozycji, Porównanie wariantów, Log audytu, Powiadomienia, Ustawienia (język; reszta w M4 część 2).

## Publiczny interfejs
- `src/api/client.ts` – interfejs `Api` i implementacja HTTP (`/v1`, bearer z `localStorage.bomagent_token` lub `VITE_DEV_TOKEN`, SSE przez `fetch`).
- `src/api/mock.ts` – `MockApi`: dwie organizacje w pamięci, przebiegi odtwarzane z prawdziwych wyników `bomagent run` (symulator modelu). Do review i E2E bez backendu.
- `src/api/schema.gen.ts` – typy wygenerowane z kontraktu `services/api/openapi.json` (`pnpm gen:api`).

## Uruchomienie
```bash
pnpm --filter @bomagent/web dev:mock   # bez backendu, dane przykładowe
pnpm --filter @bomagent/web dev        # z API na :8000 (just up), token: localStorage.bomagent_token
```

## Testy
```bash
pnpm --filter @bomagent/web typecheck
pnpm --filter @bomagent/web test       # vitest + Testing Library (w tym przełączanie organizacji)
pnpm --filter @bomagent/web e2e        # Playwright + axe (WCAG 2.1 AA), desktop + mobile smoke
PW_CHANNEL=chrome pnpm --filter @bomagent/web e2e   # gdy jest tylko systemowy Chrome
E2E_BASE_URL=http://localhost:5173 pnpm --filter @bomagent/web e2e   # przeciw działającemu stosowi
node e2e/shot.mjs                      # zrzuty ekranów do review (serwer mock na :5179)
```

## Ograniczenia (świadome)
- Brak logowania OIDC w UI (PKCE) – M4 część 2; teraz token wklejany do `localStorage`.
- Przełącznik organizacji działa w trybie mock; w trybie HTTP organizacja wynika z tokenu.
- Komunikaty reguł walidacji są po angielsku (z backendu) – tłumaczenie po `rule_id` w kolejnym kroku.
- Bundle ~585 kB (mock i dane przykładowe w paczce) – podział na chunki przy M6.
