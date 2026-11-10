# M5 – Frontend (`apps/web`)

## Brainstorming (pytania i odpowiedzi z dokumentów)
| Pytanie | Odpowiedź | Źródło |
|---|---|---|
| Stos | React + Vite + TanStack Router/Query/Table + Tailwind + komponenty w stylu shadcn w `packages/ts/ui` | ADR-0014 |
| Logowanie lokalnie | mock IdP API (`/v1/dev/token`); w chmurze Cognito Hosted UI + PKCE (M6) | ADR-0005, DECISIONS_LOG |
| Postęp na żywo | SSE przez `fetch` (EventSource nie wysyła nagłówka Authorization) | ADR-0015 |
| Lista modeli w modalu | nowy `GET /v1/models` – ta sama reguła co walidacja `POST /v1/runs` | katalog modeli (M2) |
| E2E bez Dockera | `tools/devstack.py`: API + workery w jednym procesie, nowa baza; w CI stos compose | TESTING.md |

## Plan wizualny (skill frontend-design, przegląd vs „generyczny” wzorzec)
- **Paleta:** papier `#ECEFF2` (chłodna szarość, nie krem), powierzchnie `#FFFFFF`, atrament `#18212B` (akcja główna – nie zielony, żeby nie mylić z regułą), linie `#D3D9DF`, fiolet LLM `#5B3FD6`, zieleń soldermaski `#13704A`, bursztyn `#A35A00`, czerwień `#B42318`.
- **Typografia:** Bricolage Grotesque 800 tylko w powitaniu i tytułach; IBM Plex Sans w interfejsie; Plex Mono wyłącznie dla danych technicznych (oznaczenia, MPN, obudowy) – nie dla etykiet.
- **Jedyny odważny element:** pasek pochodzenia (4 px) przy każdym wierszu BOM w kolorze tego, kto zdecydował (agent / reguła / plik / człowiek), powtórzony w pasku „Kto zdecydował” i w szkicach potoku na kartach wariantów w modalu. Reszta spokojna: promienie wg hierarchii (panel 18 > karta 12 > kontrolka 8), bez etykiet WIELKIMI LITERAMI, bez gradientów, bez strzałek w przyciskach.
- **Zmiany po przeglądzie:** zrezygnowałem z dużych liczb w kartach statystyk w stanie pustym (zamiast „0” – zaproszenie do działania, jak w UX_GUIDELINES), a panel pozycji jest szufladą poniżej 1536 px, bo przy panelu obok tabeli kolumna MPN była ucinana.

## Zakres v1 (zrobione)
Logowanie (lokalne), onboarding (organizacja, dołączenie kodem zaproszenia), shell z przełącznikiem organizacji, Start (powitanie, szablony urządzeń z własnymi ilustracjami SVG, karty z pustymi stanami), Projekty (lista, utworzenie, upload drag & drop, statusy plików), modal Nowy przebieg (projekt, wariant A/B/oba, model z katalogu, wymagania urządzenia), Przebieg na żywo (SSE, liczniki), BOM (tabela, filtr „tylko z uwagami”, panel pochodzenia, poprawka → nowa wersja + wiedza organizacji), eksport CSV, Log audytu (filtr, weryfikacja łańcucha), Ustawienia (członkowie i role, zaproszenia, klucze API z rotacją, zużycie i limity, SSO – informacja), PL/EN.

Porównanie wariantów A/B: metryki przebiegów (pozycje, wywołania LLM, tokeny, koszt, uwagi) i różnice per oznaczenie (wartość, producent, MPN) z kolorem pochodzenia.

## Do zrobienia w M5 (kolejne kroki)
Porównanie z BOM referencyjnym (P/R/F1 – wymaga wgrania referencji i endpointu ewaluacji), Baza wiedzy (dokumenty organizacji, stan indeksowania – wymaga endpointów KB w API), oś kroków przebiegu z rodzajem kroku (wymaga zdarzeń kroków w SSE), logowanie Cognito (PKCE) razem z M6, zrzuty ekranów w PR.
