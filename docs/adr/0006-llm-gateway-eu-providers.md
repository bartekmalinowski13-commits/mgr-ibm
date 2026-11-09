# ADR-0006: LLM Gateway (LiteLLM) i dostawcy z przetwarzaniem w UE

Status: Zaakceptowany · 2026-11-09

## Kontekst
Wymagane modele zamknięte najwyższej klasy (Anthropic, OpenAI) i otwarte; wszystko w UE; porównanie w pracy.

## Decyzja
Wszystkie wywołania przez LiteLLM. Katalog modeli w konfiguracji z atrybutami `license_class` (closed/open-weight) i `residency`. Dostawcy: Bedrock (Claude przez profil EU lub in-region; modele open-weight), Azure OpenAI w trybie Data Zone Standard EU, Mistral (UE), vLLM self-hosted, Ollama w dev. Allowlista egress, budżety per tenant, brak treningu na danych klientów. ID modeli weryfikowane przy włączaniu (dostępność regionalna się zmienia).

## Konsekwencje
Jeden punkt egzekwowania polityk i pomiaru kosztów; łatwa wymiana modeli w eksperymentach. Ryzyko: gateway jako pojedynczy punkt awarii – min. 2 zadania, health checki, fallback.

## Rozważane alternatywy
Bezpośrednie SDK dostawców w kodzie (rozproszone polityki, trudny audyt).
