# Wytyczne UX/UI

Źródła: zalecenia UX-owca (Mobbin + skill frontend-design + shadcn/ui), inspiracja **Homerun (web)** z Mobbin (`inspiration/mobbin-homerun-home-and-modal.png`), wcześniejszy prototyp przepływu (`prototype/v0-flow.html`).

> Inspiracja, nie kopia. Bierzemy **wzorce** (układ, hierarchię, zachowania), nie grafiki, ilustracje, nazwy ani identyfikację wizualną Homerun.

## 1. Narzędzia
1. **Skill `frontend-design`** (Anthropic) – obowiązkowy przy każdej pracy nad UI. Jego zasady: zaplanuj tokeny (kolor, typografia, układ) przed kodem, unikaj generycznych wzorców, jedna odważna rzecz na ekran, reszta spokojna, krytyka zrzutów ekranu.
2. **shadcn/ui** – baza komponentów (Radix + Tailwind), kopiowana do `packages/ts/ui` i dostosowana do naszych tokenów. Inne biblioteki z listy UX-owca (Chakra UI, MUI, Mantine, Ant Design, HeroUI) – tylko jako źródło wzorców, **nie** jako zależności (ADR-0014).
3. **Mobbin** – referencje wzorców. Jeśli jest płatne konto, podłącz Mobbin MCP w Claude Code i przed projektowaniem ekranu wyszukaj 3–5 referencji (np. „empty state dashboard B2B”, „create modal two-column form”, „data table with side panel”). Zapisz linki w opisie PR.

## 2. Co bierzemy z Homerun (analiza screena)
| Wzorzec w Homerun | Jak stosujemy w BOM Agent |
|---|---|
| Lewy sidebar: przełącznik organizacji na górze (awatar + nazwa + strzałka), ikony + etykiety, sekcje „Your jobs” i nazwa organizacji, logo marki na dole | Sidebar: **przełącznik organizacji** (multi-tenant!), nawigacja główna: Start, Powiadomienia, Szukaj, **+ Nowy przebieg** (akcja w nawigacji); sekcja „Twoje projekty” (ostatnie); sekcja organizacji: Projekty, Przebiegi, Zestawienia BOM, Baza wiedzy, Reguły, Log audytu, Analizy, Ustawienia |
| Górny pasek: tytuł strony po lewej, po prawej pigułka „15 days left in your trial · View plans” | Tytuł/breadcrumb; po prawej pigułka planu (np. „Pilot: 15 dni · Zobacz plany”) i zużycie limitu LLM |
| Duże, ciężkie powitanie „Hi there Sam” – typografia jako element graficzny | „Cześć, Bartek” w kroju display o dużej wadze; jedyne miejsce z tak dużą typografią na ekranie |
| Panel „Create a new job” z karuzelą szablonów (karta „No template” z plusem + karty z okładkami), zamykany krzyżykiem | Panel **„Nowy przebieg BOM”**: karta „Pusty projekt” (+) i szablony przykładowych urządzeń (EKG noszony, pulsoksymetr, wzmacniacz EEG, pompa infuzyjna…) z **własnymi** okładkami (ilustracje SVG o tematyce PCB/sensorów) |
| Rząd kart-statystyk, które w stanie pustym są zaproszeniem („No active jobs”, „No candidates”, „1 to-do”) | Karty: aktywne przebiegi, pozycje do przeglądu, otwarte uwagi walidacji, projekty – **puste stany zawsze z akcją**, nie z pustą liczbą „0” |
| Sekcja „Guides” z ilustrowanymi kartami | „Przewodniki”: jak przygotować projekt KiCad, czym różnią się warianty A i B, checklista IEC 60601, jak eksportować IPC-2581 z Altium/Allegro |
| Modal „Create new job”: etykiety po lewej, pola po prawej, gwiazdka wymaganych, selecty, **karty-radio z mini-ilustracjami** („Job post and application form” / „Only application form”), stopka: Cancel + zielony Continue | Modal **„Nowy przebieg”**: Nazwa*, Projekt (select / upload), Wymagania urządzenia (część aplikacyjna, zasilanie), Model (zamknięty / open-weight), **Wariant jako karty-radio z mini-diagramem potoku** (A: 100% LLM / B: hybryda / Oba + porównanie); stopka: Anuluj + Dalej |
| Ciepłe, jasne tło, białe karty z delikatną ramką, duże zaokrąglenia kart, mało cieni | Jasne neutralne tło, białe powierzchnie, ramki 1px, promień zależny od hierarchii (karty duże > przyciski > znaczniki) |
| Akcent fioletowy (trial) i zielony (primary) | Patrz kolory semantyczne niżej – zachowujemy rozróżnienie pochodzenia decyzji |

## 3. Tokeny (punkt startowy – do dopracowania skillem frontend-design)
**Kolory semantyczne (stałe w całym produkcie i na diagramach):**
- `provenance.llm` – fiolet (decyzja agenta LLM)
- `provenance.rule` – zieleń soldermaski (decyzja reguły deterministycznej)
- `status.ok` / `status.warn` / `status.error` – zieleń / bursztyn / czerwień, zawsze z ikoną i tekstem (nie tylko kolor)
- `action.primary` – ciemny atrament (nie zielony, żeby nie mylił się z `provenance.rule`)
- tło: jasna, chłodna szarość papieru; powierzchnie: biel; ramki: szarość 1px

**Typografia:** krój display o dużej wadze do powitania i nagłówków stron (propozycja: Bricolage Grotesque 800, licencja OFL); krój tekstowy: IBM Plex Sans; dane techniczne (MPN, oznaczenia, footprinty): IBM Plex Mono. Skala typograficzna wg „The Elements of Typographic Style”, długość linii tekstu < 80 znaków.

**Bez:** etykiet WIELKIMI LITERAMI nad każdym nagłówkiem, strzałek „→” w przyciskach, numerowanych znaczników tam, gdzie treść nie jest sekwencją, gradientów dekoracyjnych, identycznych kart z identycznym cieniem.

## 4. Ekrany (minimum v1)
1. **Start** (jak wyżej).
2. **Projekty** – lista + upload (drag & drop folderu, wykrycie formatu, komunikat o ograniczeniach formatu).
3. **Nowy przebieg** – modal (jak wyżej).
4. **Przebieg na żywo** – oś kroków z kropkami w kolorze pochodzenia, liczniki czasu/tokenów/kosztu, SSE; dla trybu „Oba” – dwie kolumny.
5. **BOM** – tabela (TanStack Table): pasek pochodzenia z lewej strony wiersza, filtry „tylko z uwagami”, edycja inline z zapisem jako wiedza organizacji; **panel boczny** pozycji: uzasadnienie, cytaty z bazy wiedzy (z linkiem do strony datasheetu), wynik każdej reguły, historia zmian.
6. **Porównanie wariantów** – metryki vs BOM referencyjny, różnice per pozycja.
7. **Baza wiedzy** – dokumenty organizacji + przegląd korpusu globalnego (tylko odczyt), stan indeksowania.
8. **Log audytu** – filtrowanie po użytkowniku, obiekcie, czasie; eksport.
9. **Ustawienia organizacji** – członkowie i role, SSO (SAML/OIDC), klucze API, limity i zużycie, retencja danych.
10. **Onboarding** – rejestracja organizacji, weryfikacja domeny, pierwszy projekt z szablonu.

## 5. Teksty (UX writing)
Zdania pisane prostym językiem, z perspektywy użytkownika; przycisk mówi, co się stanie („Uruchom przebieg”, „Eksportuj CSV”), toast używa tego samego czasownika („Wyeksportowano CSV”). Błędy mówią, co się stało i jak to naprawić („Plik .brd nie jest obsługiwany bezpośrednio. Wyeksportuj IPC-2581 z Allegro i wgraj go tutaj.”). Pusty stan = zaproszenie do działania. PL i EN od początku (i18n).

## 6. Jakość
WCAG 2.2 AA (kontrast, focus widoczny, pełna obsługa klawiaturą, `prefers-reduced-motion`), responsywność do 375 px (tabela BOM przewijana poziomo, panel boczny jako szuflada), stany ładowania (skeletony), stany błędów i puste dla każdej listy. Każdy ekran: zrzut w Playwright w PR + test axe.
