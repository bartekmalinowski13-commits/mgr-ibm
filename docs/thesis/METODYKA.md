# Metodyka eksperymentu: co dzielą warianty A i B i jak mierzymy halucynacje

Dokument roboczy rozdziałów 5-7 (audyt TH-01). Zapisuje decyzje, które muszą być jawne, żeby
porównanie A i B było uczciwe i żeby wyniki dało się obronić.

## 1. Podział pracy: co jest wspólne, co różni warianty

Wariant A nie jest „w 100 % LLM" w sensie dosłownym. To wariant **maksymalnie oparty na LLM w
obrębie strzeżonego kontraktu**: oba warianty dostają to samo wejście i przechodzą przez tę samą
„podłogę bezpieczeństwa", a różni je tylko to, kto podejmuje decyzje merytoryczne.

| Element | A (LLM) | B (hybryda) | Wspólny? | Gdzie w kodzie |
|---|---|---|---|---|
| Parsowanie plików (KiCad, EDIF, ...) | tak | tak | **tak** | `bomagent_cad` |
| Rodzaj elementu, obudowa z footprintu | tak | tak | **tak** | `kind_of`, `package_from_footprint` |
| Walidacja schematu wyjścia, współczynnik poprawek (`lines_to_items` odrzuca wadliwe linie) | tak | tak | **tak** | `bomagent_agents.contracts` |
| **Reguła „MPN tylko z dowodów"** (`guard_mpns`) | tak | tak | **tak** | `runtime_base.AgentContext.guard_mpns` |
| Metryki i zbiory odniesienia | tak | tak | **tak** | `bomagent_eval` |
| Grupowanie komponentów w linie BOM | LLM (`extract_group`, `compose`) | deterministyczne (`bom-core`) | nie | `variant_a.py` / `variant_b.py` |
| Wybór MPN spośród kandydatów z KB | LLM | LLM po deterministycznym zawężeniu kandydatów | nie | `mpn_select` |
| Walidacja BOM | LLM (`validate`) | pakiet reguł `core@1.0.0` + naprawa LLM (`repair`) | nie | `rules`, `repair` |

Uzasadnienie wspólnej części: rozbieżność wyników ma wynikać z **podziału decyzji**, nie z tego,
że jeden wariant ma zabezpieczenie, którego drugi nie ma. Reguła MPN-tylko-z-dowodów jest
wymogiem produktu (nie wolno wypuścić numeru części wymyślonego przez model), więc obowiązuje
oba warianty identycznie.

## 2. Dwie miary halucynacji (PB2)

Ponieważ strażnik usuwa z końcowego BOM każdy MPN spoza dowodów, wskaźnik policzony **na
końcowym BOM** jest bliski zera dla obu wariantów z konstrukcji - nie różnicuje ich. Zjawisko,
które da się zmierzyć, to **próba halucynacji**: model zaproponował MPN, którego nie ma w żadnym
pobranym dowodzie, i strażnik go odrzucił (zapisuje to ustalenie `agent.mpn_rejected`).

| Metryka | Definicja | Rola |
|---|---|---|
| `attempted_mpn_hallucination_rate` | odrzucone decyzje MPN / wszystkie decyzje MPN agentów | **główna miara PB2** |
| `mpn_hallucination_rate` | MPN w końcowym BOM spoza wszystkich zaufanych katalogów / MPN w końcowym BOM | miara **resztkowa** (wtórna; kontrola, że strażnik działa) |
| `mpn_out_of_reference_rate` | MPN w końcowym BOM spoza BOM odniesienia | wtórna |

„Decyzja MPN agenta" to MPN, który agent wybrał (proweniencja `agent`) i który został w BOM,
**plus** każdy odrzucony. MPN odczytany z pliku projektu (proweniencja `parser`) nie jest decyzją
agenta i nie wchodzi do mianownika. Gdy agent nie podjął żadnej decyzji MPN, wskaźnik jest
niezdefiniowany (`NaN`), a nie zerowy; ta sama zasada dotyczy BOM bez ustaleń (np. goła lista
pozycji). Metryka trafia do tabel i rysunków `bomagent experiment` (`KEY_METRICS`,
`QUALITY_FIGURE`) obok miary resztkowej.

## 3. Statystyka i ograniczenia

- Jednostką analizy jest **projekt** (średnia z powtórzeń), test permutacyjny sparowany; plan
  szczegółowy: `PREREJESTRACJA.md` (po jego powstaniu, audyt TH-04).
- Hosting modeli (Bedrock, Mistral) nie gwarantuje determinizmu nawet przy temperaturze 0:
  powtarzalność jest mierzona (`repeats`), nie zakładana.
- Zbiór własnych projektów (z kontrolowanym wstrzykiwaniem błędów) nie jest łączony z realnymi
  projektami open-source w statystykach nagłówkowych (audyt TH-03).

## 4. Dalsze kroki wynikające z audytu (jeszcze niezrobione)

1. Ablacja **A bez strażnika** (`A-unguarded`): ta sama macierz z wyłączoną regułą MPN-z-dowodów,
   żeby policzyć, ile faktycznie usuwa strażnik (rozdział 7 i argument produktowy).
2. Raport pokrycia przez pakiet reguł rodzajów wstrzykniętych błędów (audyt TH-06/TH-10).
3. Odtworzenie wyników na pgvector + prawdziwych osadzeniach zamiast `InMemoryRetriever` (TH-02).
