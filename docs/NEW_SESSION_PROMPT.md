# Prompt for a new session (copy everything below the line)

---

Kontynuujesz pracę nad projektem **BOM Agent** (praca magisterska + produkcyjny SaaS B2B).

**Repozytorium:** https://github.com/bartekmalinowski13-commits/mgr-ibm
**Gałąź robocza:** `claude/code-master-prompt-part-2-5651f9` (cała dotychczasowa praca jest tu; nie scalona do `main`, PR jeszcze nie otwarty — nie otwieraj go, dopóki o to nie poproszę). Pracuj i pushuj tylko na tę gałąź.

## Zacznij od czytania (w tej kolejności)

1. `docs/HANDOFF.md` — **gdzie skończyłem, co zostało do zrobienia (w kolejności), co czeka na mnie, notatki o środowisku**. To główny dokument.
2. `CLAUDE.md` — zasady nienaruszalne (izolacja tenantów, tylko UE, brak uczenia między organizacjami, sekrety, pliki klientów jako niezaufane, **zakaz wdrażania do AWS z sesji**, brak prawdziwych kluczy LLM w testach, zakaz force-push na `main`).
3. `docs/STATUS.md` — stan każdego kamienia milowego (M0–M8).
4. `docs/DECISIONS_LOG.md` — założenia przyjęte bez konsultacji; wiersze z „tak/yes" w ostatniej kolumnie czekają na moją akceptację.
5. W razie potrzeby: `docs/platform/ARCHITECTURE.md` (źródło prawdy), `docs/adr/`, `docs/platform/SECURITY.md`, `docs/platform/TESTING.md`, `docs/platform/FORMATS.md`, `docs/plans/` (plany M1–M7 i SSO), `docs/platform/runbooks/README.md`.

## Zadanie

Wykonuj otwarte zadania z `docs/HANDOFF.md`, sekcja „Next tasks for Claude Code", **w podanej kolejności**:

1. sprawdź CI ostatniego commita (SSO) i napraw to, co czerwone;
2. ponów **security review SSO** (był przerwany, brak wyników) i napraw wszystkie CRITICAL/HIGH;
3. odłożone uwagi z review (lista w `DECISIONS_LOG.md`);
4. checkpointy LangGraph w Postgresie z RLS, budżet/snapshot KB w adapterze Agent SDK;
5. przygotuj listę założeń do mojej akceptacji;
6. **na końcu**: przetłumacz pozostałe polskie dokumenty na angielski (poza `docs/thesis/`).

Proces dla każdego zadania: TDD → implementacja → review subagentem → weryfikacja (`just lint`, testy, `just openapi` po zmianach API) → aktualizacja `docs/STATUS.md` → commit i push na gałąź roboczą. Nową dokumentację pisz **wyłącznie po angielsku**. Commity: Conventional Commits, po angielsku.

## Czego nie rób

- Nie wdrażaj do AWS i nie twórz zasobów chmurowych.
- Nie commituj sekretów ani `.env`.
- Nie decyduj po cichu o rzeczach z listy „czeka na właściciela" (dane eksperymentu, dostęp do modeli UE, konto AWS/domena) — opisz je w raporcie końcowym.

## Na koniec

Zaktualizuj `docs/STATUS.md` i `docs/HANDOFF.md`, a w odpowiedzi podaj: co jest gotowe, co czeka na mnie, które założenia wymagają mojej akceptacji oraz ile % zadania jest ukończone.
