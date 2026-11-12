# Dane przykładowe - jak przejść cały proces w działającej aplikacji

> Ten dokument jest po polsku na prośbę właściciela (wyjątek od zasady "dokumenty po angielsku";
> wpis w `docs/DECISIONS_LOG.md`).

Masz pięć gotowych, małych projektów urządzeń biomedycznych. Dzięki nim od razu sprawdzisz cały
proces: **wgranie plików, wczytanie, przebieg A i B, zestawienie BOM, korekta, eksport CSV,
porównanie wariantów i ocena względem wzorca**. Wszystkie dane są własnością projektu na
licencji **CC0** (domena publiczna), nie zawierają cudzych projektów.

| Projekt | Format plików | Po co |
|---|---|---|
| ECG front-end | KiCad 8, 3 arkusze | największy: hierarchia, element DNP, części bez MPN |
| EEG 2-channel | KiCad 9 | ten sam arkusz użyty dwa razy |
| Pulse oximeter | KiCad 6 | najstarszy format, najmniejszy projekt |
| ECG patch | EDIF (nie KiCad) | wejście tylko z netlisty |
| Digital thermometer | PDF z tabelą BOM | wejście tylko z tabeli; jeden element (termistor) nie jest w bazie wiedzy |

## Sposób 1 - projekty dodane automatycznie (najprostszy)

Każda **nowa organizacja** dostaje pięć projektów z prefiksem **`[Sample]`** (np. `[Sample] ECG
front-end`) od razu po założeniu. Pliki są już wczytane i sprawdzone, więc od razu możesz
uruchamiać przebiegi.

**Twoja istniejąca organizacja** (założona przed tą zmianą) ich jeszcze nie ma. Jako **właściciel**
(rola owner) wejdź na **Start** albo **Projekty** i kliknij **Dodaj projekty przykładowe**
(przycisk pokazuje się, dopóki w organizacji nie ma żadnego projektu przykładowego). Klikanie
wielokrotnie niczego nie dubluje - dodawane są tylko brakujące.

> Wdrożenie: na produkcji/pilocie ustawiona jest zmienna `BOMAGENT_SEED_SAMPLES=true`
> (`deploy/supabase/fly.toml`). Ustaw `false`, jeśli nie chcesz projektów przykładowych dla
> nowych organizacji.

## Sposób 2 - wgrywanie ręczne z dysku

Pliki leżą w repozytorium w katalogu **`evals/samples/<projekt>/`**. W aplikacji:

1. **Projekty -> nazwa projektu -> Utwórz projekt** (np. `Mój ECG`).
2. W projekcie przeciągnij **wszystkie pliki projektowe** z katalogu (np. dla ECG front-end:
   `ecg-frontend.kicad_sch`, `afe.kicad_sch`, `power.kicad_sch`, `ecg-frontend.kicad_pro`;
   dla ECG patch: `ecg-patch.edf`; dla termometru: `thermometer-bom.pdf`).
   **Nie wgrywaj** `reference_bom.csv` ani `README.md` do projektu - wzorzec wgrywasz dopiero
   w kroku 6.
3. Poczekaj, aż przy plikach pojawi się status **Gotowy** (kilka sekund).

## Krok po kroku - cały proces

1. **Wgranie i wczytanie** - projekt `[Sample] ...` -> sekcja **Pliki projektu**: status
   **Gotowy** i liczba komponentów (np. 30 dla ECG front-end).
2. **Przebieg** - **Nowy przebieg** (albo **Uruchom przebieg** w projekcie), wybierz projekt i
   wariant **Oba i porównanie** (A = tylko LLM, B = hybryda). Wypełnij wymagania (część
   aplikacyjna, zasilanie) lub użyj szablonu ze Startu. Na pilocie model LLM jest
   deterministycznym modelem testowym (bez kosztów), więc wyniki służą do sprawdzenia
   przepływu, nie jakości modeli.
3. **BOM** - po zakończeniu otwórz przebieg: tabela pozycji, pochodzenie każdego pola
   (z projektu / reguła / baza wiedzy / agent / użytkownik) i uwagi walidacji.
4. **Korekta** - kliknij pozycję i popraw np. MPN lub producenta (podaj powód). Powstaje
   nowa wersja BOM; poprawka jest zapisana jako wiedza **tylko Twojej organizacji**.
5. **Eksport** - **Eksportuj CSV**.
6. **Ocena względem wzorca** - w przebiegu panel **Porównanie z BOM referencyjnym** ->
   **Wgraj BOM referencyjny** i wskaż `evals/samples/<projekt>/reference_bom.csv`. Zobaczysz
   F1 pozycji, precyzję, czułość i pokrycie MPN. Plik nie jest zapisywany.
7. **Porównanie wariantów** - w projekcie **Porównaj warianty A i B** (potrzebne dwa gotowe
   przebiegi). Ten sam wzorzec możesz wgrać do obu przebiegów.

## Usuwanie

Projekt przykładowy ma plakietkę **Przykład**. Otwórz go i kliknij **Usuń projekt przykładowy**
(usuwa pliki, przebiegi i wersje BOM; nie można cofnąć). Dotyczy to tylko projektów
przykładowych. Projekty przykładowe **nie liczą się do limitu projektów** planu; ich pliki
(razem ok. 100 KB) liczą się do limitu miejsca.

## Gdy coś nie działa

- Brak przycisku **Dodaj projekty przykładowe**: nie jesteś właścicielem organizacji, albo
  organizacja już ma projekt przykładowy, albo wdrożenie ma `BOMAGENT_SEED_SAMPLES=false`
  (wtedy przycisk zwraca błąd 404).
- Plik zostaje w statusie **Sprawdzanie** dłużej niż minutę: sprawdź, czy działa proces
  roboczy wczytywania (na pilocie jest w tym samym kontenerze; logi `fly logs`).
- Termometr (PDF) ma pewność wczytania poniżej 1,0 - to zamierzone: tabela jest czytana z układu
  strony, więc pozycje trzeba przejrzeć.

Szczegóły techniczne: `evals/samples/README.md`, `services/api/README.md` (sekcja "Sample
projects").
