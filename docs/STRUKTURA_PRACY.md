# Struktura pracy magisterskiej

**Temat:** Porównanie systemu wieloagentowego opartego na dużych modelach językowych z systemem wieloagentowym z elementami deterministycznymi w zastosowaniu do generowania BOM urządzeń biomedycznych

**Opiekun:** dr inż. Magdalena Mazur-Milecka, Katedra Inżynierii Biomedycznej, WETI PG

Szablon w Wordzie: [`thesis/Praca_magisterska_Bartosz_Malinowski_szablon.docx`](../thesis/Praca_magisterska_Bartosz_Malinowski_szablon.docx). Format jak w pracy inżynierskiej: Arial 10 pt, interlinia 1,5, wyjustowanie, wcięcie akapitu, rozdziały wielkimi literami od nowej strony, numeracja `1.` / `1.1.` / `1.1.1.`, cytowania `[n]`, numer strony w prawym dolnym rogu.

## Część wstępna
- Strona tytułowa (logo PG/ETI, dane studenta, tytuł PL/EN, opiekun)
- Oświadczenie (wkleić aktualną treść z Moja PG)
- Streszczenie + słowa kluczowe + dziedzina OECD
- Abstract + keywords
- Spis treści (pole Worda – aktualizować)
- Wykaz ważniejszych skrótów i pojęć

## Rozdziały

| # | Rozdział | Zawartość | Moduł projektu / zadanie z karty tematu |
|---|---|---|---|
| 1 | Wstęp i cel pracy | motywacja, cel i zakres, pytania badawcze PB1–PB3, hipoteza H1, układ pracy | — |
| 2 | Przegląd literatury | agenci LLM, MAS, RAG, podejścia hybrydowe, LLM w EDA, BOM w urządzeniach medycznych (MDR, ISO 13485, IEC 60601), ewaluacja (RAGAS), luka badawcza | przegląd literatury (**efekt na koniec semestru**) |
| 3 | Zbiór danych i baza wiedzy | otwarte projekty KiCad, BOM referencyjne, datasheety, budowa indeksu RAG, zbiór ewaluacyjny | baza wiedzy + zbiór ewaluacyjny (**efekt na koniec semestru**) |
| 4 | Narzędzia dostępu do plików CAD | struktura plików KiCad, parser, narzędzia dla agentów (function calling / MCP), testy | prototyp modułu analizy CAD (**efekt na koniec semestru**) |
| 5 | Projekt i implementacja systemu | wymagania, architektura ogólna (Rys. 5.1), wariant A, wariant B, komponenty wspólne, UI, stos | implementacja dwóch wariantów |
| 6 | Metodyka badań | plan eksperymentu, metryki (Tab. 6.1), konfiguracja, analiza statystyczna | eksperymenty |
| 7 | Wyniki i dyskusja | jakość BOM, halucynacje, koszt, powtarzalność, analiza błędów, odpowiedzi na PB | analiza wyników |
| 8 | Podsumowanie i wnioski | wnioski, ograniczenia, dalsze prace | wnioski |

## Część końcowa
- Bibliografia (5 pozycji z karty tematu jako start)
- Wykaz rysunków, wykaz tabel
- Dodatek A – prompty i profile agentów
- Dodatek B – schemat danych BOM (JSON Schema)
- Dodatek C – repozytorium i instrukcja uruchomienia

## Pytania badawcze
- **PB1** – czy wariant hybrydowy daje wyższą poprawność pozycji i pól BOM (MPN, ilość, wartość, footprint)?
- **PB2** – jak warianty różnią się odsetkiem halucynacji?
- **PB3** – jaki jest koszt (tokeny, czas, wywołania) i powtarzalność obu podejść?
- **H1** – wariant hybrydowy osiąga wyższe F1 i mniej halucynacji przy niższym koszcie.
