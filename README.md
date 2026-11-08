# Praca magisterska – BOM Agent

**Porównanie systemu wieloagentowego opartego na dużych modelach językowych z systemem wieloagentowym z elementami deterministycznymi w zastosowaniu do generowania BOM urządzeń biomedycznych**

Bartosz Malinowski · opiekun: dr inż. Magdalena Mazur-Milecka · WETI, Politechnika Gdańska

## Zawartość
| Ścieżka | Co to jest |
|---|---|
| `thesis/Praca_magisterska_Bartosz_Malinowski_szablon.docx` | szablon pracy w Wordzie (format jak praca inżynierska, pełna struktura rozdziałów z notatkami „[Do napisania]”) |
| `docs/STRUKTURA_PRACY.md` | struktura pracy, mapowanie rozdziałów na zadania z karty tematu, pytania badawcze |
| `docs/ARCHITEKTURA.md`, `docs/architektura.html`, `docs/img/architektura.*` | architektura systemu: wariant A (100% LLM) vs wariant B (hybrydowy) |
| `ui/index.html` | klikalny prototyp interfejsu: projekt → konfiguracja → przebieg agentów → BOM → porównanie (dane przykładowe) |
| `tools/` | skrypty generujące diagram (`arch.py`) i szablon DOCX (`build_docx.js`) |

## Regeneracja
```bash
python3 tools/arch.py docs/img/architektura.svg && rsvg-convert -z 2 docs/img/architektura.svg -o docs/img/architektura.png
node tools/build_docx.js . thesis/Praca_magisterska_Bartosz_Malinowski_szablon.docx
```

## Efekt na koniec semestru (z karty tematu)
- [ ] rozdział przeglądowy (rozdz. 2)
- [ ] baza wiedzy z dokumentacji technicznej + zbiór ewaluacyjny (rozdz. 3)
- [ ] prototyp modułu analizy plików CAD (rozdz. 4)
