# Prerejestracja analizy eksperymentu (wariant A vs B)

Status: **szkic do zatwierdzenia przez autora pracy** - ma zostać zamrożony (commit z tagiem
`prereg-v1`) **przed** pierwszym uruchomieniem macierzy na prawdziwych modelach. Każda późniejsza
zmiana trafia do sekcji „Odstępstwa" z datą i uzasadnieniem; nie edytujemy zamrożonych sekcji.
Dokument opisuje to, co kod już liczy (`bomagent experiment run`, `report.md`, `tables/paired.csv`).

## 1. Pytania i hipotezy

- **H1 (jakość):** wariant B (hybrydowy) daje wyższą zgodność BOM z BOM-em referencyjnym niż A
  (F1 pozycji).
- **H2 (halucynacje):** B ma niższy odsetek *prób* użycia numeru części, którego nie ma w bazie
  wiedzy (`attempted_mpn_hallucination_rate`; strażnik odrzuca takie numery w obu wariantach, więc
  mierzymy próby, nie wynik końcowy - patrz `METODYKA.md`).
- **H3 (koszt):** B ma niższy koszt jednego BOM-a w EUR (`cost_eur`).
- Kierunek hipotez jest jednostronny co do interpretacji, ale testy są **dwustronne**
  (konserwatywnie).

## 2. Jednostka analizy

Jednostką statystyczną jest **projekt (design)**, nie pojedynczy przebieg: powtórzenia tego samego
projektu nie są niezależne, więc uśredniamy je w obrębie projektu i porównujemy pary A/B na
poziomie projektów (n = liczba projektów w zbiorze ewaluacyjnym). Przy małym n najmniejsze
osiągalne p w teście permutacyjnym to 2 / 2^n - raportujemy to w `report.md`.

## 3. Metryki

**Pierwotne (rodzina z korektą Holma):**

| metryka | kierunek lepszy |
|---|---|
| `line_f1` - F1 pozycji BOM | wyższy |
| `attempted_mpn_hallucination_rate` | niższy |
| `cost_eur` - koszt jednego BOM-a | niższy |

**Wtórne (bez korekty, raportowane opisowo, interpretowane ostrożnie):** pozostałe metryki z
`KEY_METRICS` (precyzja/recall pozycji, `designator_f1`, `acc_mpn`, `acc_value`, `mpn_coverage`,
`mpn_out_of_reference_rate`, `mpn_hallucination_rate`, liczba wywołań i tokenów, czas), a także
skuteczność walidacji na wstrzykniętych błędach (`detection_rate`, `false_alarm_rate`) z
podziałem na klasy błędów i informacją, czy reguły deterministyczne pokrywają daną klasę (TH-06).

## 4. Analiza pierwotna

- Test: dwustronny, dokładny **test permutacyjny par (zamiana znaków)** na różnicach B − A
  uśrednionych po projektach (Monte Carlo powyżej 16 projektów); przedział ufności 95 %
  metodą percentylową bootstrap różnic.
- **Korekta wielokrotności:** metoda Holma-Bonferroniego, w obrębie rodziny pierwotnej,
  **osobno dla każdego modelu** (3 hipotezy). Raportujemy p surowe i `p (Holm)`; za wynik
  pierwotny uznajemy `p (Holm)` < 0,05.
- **Wielkość efektu:** standaryzowana różnica par d_z = średnia(B − A) / odch. std.(B − A),
  obok różnicy surowej (nie zastępuje jej). Przy zerowym rozrzucie różnic d_z jest nieokreślone.

## 5. Analiza wrażliwości

- **Bootstrap klastrowy:** próbkowanie projektów ze zwracaniem, a następnie powtórzeń wewnątrz
  wybranych projektów; statystyka = średnia ze średnich projektów (każdy projekt waży tyle samo
  co w analizie pierwotnej). Raportowany jako `cluster CI`. Służy do sprawdzenia, czy wniosek
  przetrwa uwzględnienie zmienności między powtórzeniami; nie zmienia decyzji z sekcji 4.
- Modele mieszane / GEE na poziomie pozycji BOM są **poza zakresem** tej prerejestracji
  (przy n = 6-8 projektów dają niestabilne oszacowania); rozważane tylko jako analiza
  eksploracyjna w rozdziale 7, jawnie oznaczona.

## 6. Rodziny i modele

Modele (zamknięty i otwarty, co najmniej po jednym z UE) analizujemy **osobno**; nie łączymy ich
w jedną rodzinę testów. Porównanie klas modeli (zamknięty vs otwarty) to analiza opisowa, bez
testu.

## 7. Zasady, których nie łamiemy

1. Wszystkie przebiegi z macierzy są raportowane, także nieudane (liczone w `statuses`).
2. Brak „podglądania": analiza pierwotna jest uruchamiana raz, na kompletnej macierzy.
3. Ziarno (`seed`) i `manifest.json` (commit, wersje promptów, identyfikatory modeli, ustawienia
   próbkowania, stos wyszukiwania i skrót zawartości bazy wiedzy) są zapisywane z każdym
   uruchomieniem.
4. Modele hostowane nie są deterministyczne nawet przy temperaturze 0 - powtórzenia mierzą
   zmienność między przebiegami.
5. Ograniczenia znane przed startem: wyszukiwanie w eksperymencie to hashowane embeddingi bez
   semantyki (TH-02), wstrzykiwane błędy są syntetyczne, a ocena autora-i-badacza w jednej osobie
   (TH-03, podwójna weryfikacja zbioru).

## 8. Odstępstwa od planu

(brak - uzupełniane po zamrożeniu)
