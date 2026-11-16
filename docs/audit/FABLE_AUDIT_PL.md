# Fable Audit — mgr-ibm / BOM Agent

**Rodzaj:** niezależny audyt oprogramowania (architektura rozwiązania, bezpieczeństwo, gotowość produkcyjna, trafność badawcza)
**Audytowana rewizja:** `main` na `1a763f3` (2026-11-16), gałąź `claude/blissful-sagan-aolsyd`
**Audytor:** Claude (Fable 5.1) w roli audytora systemów IT i solution architekta
**Wersja angielska:** [`FABLE_AUDIT_EN.md`](FABLE_AUDIT_EN.md)

> Założenie zakresu zadane przez właściciela: wszystko, co istnieje w repozytorium (M0–M8, ścieżka AWS, pilot Supabase, narzędzia eksperymentu) **zostanie dokończone zgodnie ze specyfikacją**. Audyt ocenia więc projekt i kod takimi, jakie są, oraz wylicza, czego brakuje do (a) obronialnej pracy magisterskiej i (b) produkcyjnego, wielodostępnego (multi-tenant) SaaS dla firm projektujących urządzenia medyczne.

---

## 0. Streszczenie dla zarządu

Repozytorium jest nietypowo dojrzałe jak na projekt magisterski: monorepo z 14 pakietami/serwisami Python i 3 pakietami TypeScript, wymuszone Row-Level Security na każdej tabeli tenantów, dziennik audytu z łańcuchem haszy, transakcyjny outbox, sandbox parserów z limitami zasobów, strażnik „tylko UE” dla LLM, 17 ADR-ów, wdrożenie CDK z 10 stosami, działający pilot na Fly.io + Supabase oraz runner eksperymentu z poprawnym planem statystycznym. Kontrole statyczne (ruff, mypy `--strict`, import-linter, biome, tsc) są czyste, a zestawy testów jednostkowych zielone (zweryfikowane w tej sesji, §9).

Luka między „doskonałym fundamentem” a „produkcyjnym SaaS” jest jednak realna. Najważniejsze ustalenia:

| # | Ustalenie | Waga | Obszar |
|---|---|---|---|
| 1 | Wariant A nie jest „100 % LLM”: deterministyczny parser, heurystyki typu/obudowy, koercja schematu i strażnik MPN „tylko z dowodów” to kod wspólny. Metryka halucynacji na finalnym BOM wynosi ~0 **z konstrukcji**; PB2 trzeba mierzyć na *próbach* halucynacji. | Wysoka (praca) | TH-01 |
| 2 | CLI eksperymentu pobiera dowody przez **embeddingi haszujące + reranking leksykalny** (`InMemoryRetriever`), a nie przez produkcyjny potok pgvector + prawdziwe embeddingi. Wyniki pracy opisywałyby RAG, którego platforma nie uruchamia. | Wysoka (praca) | TH-02 |
| 3 | Zbiór ewaluacyjny: 3 + 5 własnych małych projektów; **żaden prawdziwy otwarty projekt biomedyczny nie został jeszcze wczytany**; minimum dla planowanego testu to n ≥ 6 niezależnie zweryfikowanych projektów. | Wysoka (praca) | TH-03 |
| 4 | Działający pilot serwuje **BOM-y z fałszywego modelu bez żadnej informacji w UI**; koszty w katalogu modeli to wartości zastępcze. | Wysoka (produkt/praca) | UX-01, TH-07 |
| 5 | Token dostępu **i token odświeżania leżą w `sessionStorage`**; CSP SPA dopuszcza style inline → jeden XSS = pełne przejęcie konta. | Wysoka (bezpieczeństwo) | SEC-02 |
| 6 | Proces API trzyma **rolę platformową**, której polityki `platform_onboarding` pozwalają wstawić członkostwo do *dowolnego* tenanta → skompromitowane API to przejęcie wszystkich organizacji. Potrzebny węższy kontrakt (funkcja onboardingu SECURITY DEFINER lub ograniczenia polityk). | Wysoka (bezpieczeństwo) | SEC-15 |
| 7 | **Brak ochrony przed nadużyciami przed kontekstem organizacji** na pilocie Supabase/Fly (brak WAF): `/v1/sso/discover`, `/v1/organizations`, `/v1/invitations/accept`, `/v1/me` są nielimitowane per IP. | Wysoka (bezpieczeństwo) | SEC-03 |
| 8 | Pilot Fly: proces parsujący dzieli **przestrzeń sieciową** kontenera; API + 3 workery + parser w **jednej maszynie 2 GB**; upload 64 MiB jest buforowany w RAM. Nigdzie nie ma skanu antywirusowego. | Wysoka (bezpieczeństwo/niezawodność) | SEC-01, SEC-13, SEC-09, ARCH-02 |
| 9 | **Brak metryk, alertów i endpointu OTel na działającym pilocie**; SLO z ARCHITECTURE §11 są niemierzalne. `source_ip` w audycie nigdy nie jest ustawiane, kotwice łańcucha nigdy nie są eksportowane. | Wysoka (operacje/zgodność) | OPS-01, OPS-02, SEC-04 |
| 10 | **Brak cyklu życia danych RODO**: brak eksportu tenanta, brak usuwania (tylko projekty przykładowe), brak retencji, brak listy podprocesorów w produkcie, brak dowodu offboardingu w audycie. | Wysoka (zgodność) | SEC-14 |
| 11 | Odroczone punkty SSO (usunięci w IdP użytkownicy zachowują dostęp ≤ 7 dni, niewygasające klucze API członków SSO, reset federacji przy deployu CDK, break-glass bez MFA) oraz **całkowity brak MFA** w wariancie Supabase. | Średnia/Wysoka | SEC-05, SEC-06 |
| 12 | Dług decyzyjny: **~60 założeń w `DECISIONS_LOG.md` czeka na akceptację**, ADR-0017 ma status „Proposed”, choć pilot na nim działa, a `ARCHITECTURE.md` opisuje stan docelowy, nie zbudowany. | Średnia | DOC-01, DOC-02 |

Oceny (szczegóły i uzasadnienie w §8): praca magisterska 8/10 · gotowość produkcyjna 5/10 · bezpieczeństwo 7/10 · użyteczność 6/10 · funkcjonalność 7/10 · niezawodność 6/10 · utrzymywalność 8/10 · obserwowalność 4/10 · wydajność i skalowalność 5/10 · testowanie 8/10 · dokumentacja 8/10 · trafność badawcza 5/10 · zgodność i prywatność 5/10 · architektura 7/10.

---

## 1. Co i jak audytowano

**Dokumenty:** `CLAUDE.md`, `README.md`, `docs/STATUS.md`, `docs/HANDOFF.md`, `docs/OWNER_CHECKLIST.md`, `docs/ROADMAP.md`, `docs/DECISIONS_LOG.md` (95 wierszy), `docs/platform/{ARCHITECTURE,SECURITY,TESTING,FORMATS}.md`, ADR-0001…0017, `docs/thesis/*`, runbooki, przewodniki właściciela, `evals/experiments/*`, `evals/reports/pilot-fake/report.md`.

**Kod (przeczytany w całości lub w częściach istotnych dla bezpieczeństwa):** `platform-common` (tenancy, db, audit, config, messaging, outbox, storage, logging, health), wszystkie 14 migracji i migrator, `services/api` (auth, authz, app, plans, idempotency, maintenance, wszystkie routery), `services/all-in-one`, `agent-worker`, `ingest-worker`, `kb-indexer`, `agents` (runtime'y A/B, adapter Claude SDK, retrieval, prompty, checkpointy), `llm` (chat, katalog, eu_guard, konfiguracja bramki), `kb` (store, safety), `cad-parsers` (sandbox, registry), `rules`, `eval`, `cli/experiment`, `apps/web` (session, supabase, oidc, api, kluczowe ekrany), `infra/cdk` (przegląd pod kątem postawy bezpieczeństwa), `deploy/*`, workflowy CI, pre-commit, Dependabot, CodeQL.

**Weryfikacja wykonana w tej sesji** (Python 3.13, Node 22, brak demona Dockera, PostgreSQL 16 bez pgvector):

| Kontrola | Wynik |
|---|---|
| `ruff check` + `ruff format --check` | czysto (275 plików) |
| `mypy --strict` dla 16 pakietów | czysto (132 pliki źródłowe) |
| `lint-imports` (2 kontrakty) | zachowane |
| `biome check`, `tsc --noEmit` (web, ui, api-client, infra) | czysto |
| `pytest -m "not integration …"` | **529 zaliczonych**, 177 pominiętych (wymagają bazy) |
| `vitest` web / api-client / infra | **49 + 2 + 36 zaliczonych** |
| Integracyjne, izolacji, kontraktowe, E2E, smoke compose | **nieuruchomione tutaj** (brak pgvector/Dockera); CI raportuje zielone na `main` |

Przeszukania: brak `dangerouslySetInnerHTML`/`eval`/`innerHTML` w SPA; brak sekretów, kluczy prywatnych i wzorców kluczy AWS w drzewie; brak `shell=True`, `pickle`, `yaml.load` w Pythonie; brak znaczników `TODO/FIXME`.

**Skala wag:** Krytyczna = wykorzystywalny wyciek między tenantami lub utrata danych (nie znaleziono); Wysoka = do naprawy przed pierwszym prawdziwym klientem lub przed eksperymentem; Średnia = przed GA / przed obroną; Niska = higiena.

**Format zadań:** każde ustalenie kończy się konkretnymi zadaniami dla modelu implementującego (Opus/Sonnet). Pracochłonność: S ≤ 1 dzień, M ≤ 1 tydzień, L > 1 tydzień. „AC” = kryteria akceptacji.

---

## 2. Co już jest mocne (zachować)

- **Izolacja tenantów to najlepsza część systemu.** Wymuszone RLS na każdej tabeli (`tenant_table_rls`), brak roli z `BYPASSRLS`, złożone klucze obce `(tenant_id, id)` (migracje 0005/0011), polityki per polecenie dla roli platformowej, test-strażnik katalogu enumerujący każdą tabelę z `tenant_id` i sprawdzający wymuszenie RLS, blokujący job izolacji w CI, klucze obiektów z prefiksem tenanta i walidacją segmentów, kontrola tenanta w kopercie kolejki (`queue_messages_envelope_tenant`).
- **Dziennik audytu** z łańcuchem haszy liczonym w bazie pod blokadą doradczą, triggery append-only, funkcja weryfikacji odmawiająca działania poza kontekstem tenanta.
- **Obsługa niezaufanych plików:** parsery nigdy nie działają w API, proces potomny `python -I` z `RLIMIT_AS/CPU`, limit czasu ściennego, okrojone środowisko, rodzic non-dumpable, limity rozmiaru projektu, defusedxml, limity dekompresji/encji, testy fuzz na wrogich danych.
- **Strażnik „tylko UE”** (`eu_guard.py`) wywala build na regionie/profilu/endpointcie spoza UE; Mistral przypięty do `api.eu.mistral.ai`; wpisy katalogu wyłączone do czasu weryfikacji.
- **Granica prompt injection:** bloki `<data>` z escapowaniem `<`/`>`, podejrzane fragmenty rankowane ostatnie i wykluczane z dowodów, structured output z walidacją schematu, MPN tylko z dowodów w każdym wariancie, narzędzia wbudowane zablokowane w adapterze Agent SDK.
- **Wzorce operacyjne:** transakcyjny outbox z dead-letteringiem, „claim” uruchomienia (`queued→running`) przy dostarczaniu co najmniej raz, reaper zawieszonych runów, klucze idempotencji związane z użytkownikiem+metodą+ścieżką+ciałem, limity planów, limity storage, rate limiting współdzielony między replikami.
- **Higiena inżynierska:** `mypy --strict`, warstwowanie import-linter, kontrola dryfu OpenAPI + Schemathesis, progi pokrycia, przypięte GitHub Actions, gitleaks + Trivy, Dependabot dla 5 ekosystemów, cdk-nag z uzasadnionymi wyjątkami, README per pakiet, kod/dokumentacja po angielsku, i18n PL/EN od początku, axe w E2E.
- **Narzędzia badawcze:** wersjonowane prompty z haszem treści, wersjonowanie pakietu reguł, pochodzenie per pole z cytowaniami, manifest eksperymentu, sparowany test permutacyjny + bootstrap CI z projektem jako jednostką, eksperyment wstrzykiwania błędów, wyjścia SVG/CSV do rozdziału 7.

---

## 3. Ustalenia bezpieczeństwa

### SEC-01 · Sandbox parsera to granica zasobów, nie więzienie sieciowe/syscall — **Wysoka (pilot), Średnia (AWS)**
**Dowód:** `packages/py/cad-parsers/src/bomagent_cad/sandbox.py` (docstring to przyznaje); ADR-0017 i `DECISIONS_LOG` 2026-11-12 L2. Na Fly proces potomny dzieli sieć kontenera i może dosięgnąć Supabase, poolera i `mgr-ibm-llm-gateway.internal:4000`.
**Ryzyko:** exploit parsera (ezdxf, pypdf, stosy XML) wykrada pliki projektowe klienta lub sonduje usługi wewnętrzne.
**Zadania:**
1. (M) Uruchamiać parsowanie w **osobnej aplikacji / grupie procesów Fly** bez wychodzącej sieci (brak `[[services]]`, zablokowany egress), konsumującej kolejkę `ingest`; aplikacja API/web nigdy nie importuje parserów. AC: `ss -tn` w parserze nie pokazuje połączeń; test integracyjny dowodzi, że kontener parsera nie rozwiązuje DNS.
2. (S) W procesie potomnym: `prctl(PR_SET_NO_NEW_PRIVS)`, `RLIMIT_NOFILE`, `RLIMIT_FSIZE` i `unshare(CLONE_NEWNET)` tam, gdzie kontener pozwala (fallback: profil seccomp z obrazu). AC: testy sandboxa asertują limity.
3. (M, AWS) Zamknąć odroczony punkt H5: definicja zadania ingest bez roli IAM do parsowania, polityka sesji ABAC per tenant dla S3.

### SEC-02 · Bearer + token odświeżania w `sessionStorage`, CSP ze stylami inline — **Wysoka**
**Dowód:** `apps/web/src/lib/session.tsx` (`write(sessionStorage, SESSION_KEY, next)` wraz z `refreshToken`), `services/all-in-one/.../app.py::spa_csp` (`style-src 'self' 'unsafe-inline'`).
**Ryzyko:** dowolny XSS (zależność, markdown w tytule datasheetu, przyszły rich text) daje długotrwałą sesję (tokeny odświeżania Supabase rotują, ale są ważne dniami).
**Zadania:**
1. (M) Wprowadzić **sesję BFF**: API wymienia kod IdP na tokeny po stronie serwera i ustawia cookie `HttpOnly; Secure; SameSite=Strict`; SPA woła same-origin z tokenem CSRF (double submit) — albo co najmniej trzymać token odświeżania po stronie serwera i dawać SPA wyłącznie 15-minutowe tokeny dostępu.
2. (S) Zacieśnić CSP: nonce/hash dla stylów (Tailwind v4 emituje jeden arkusz; atrybuty `style` w React da się zastąpić klasami), dodać `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`, HSTS `preload`.
3. (S) Dodać `ErrorBoundary` i Trusted Types (`require-trusted-types-for 'script'`) w SPA. AC: Lighthouse/Mozilla Observatory ≥ A; E2E asertuje nagłówki CSP.

### SEC-03 · Brak ochrony per IP przed kontekstem organizacji na pilocie — **Wysoka**
**Dowód:** `_rate_limit` działa tylko wewnątrz `org_context`; `DECISIONS_LOG` M4 L4 otwarte („per IP w WAF (M6)”); Fly nie ma WAF; `/v1/sso/discover` jest publiczny; `POST /v1/organizations` ograniczony tylko do 3 organizacji na użytkownika; `/v1/invitations/accept` bez limitu.
**Zadania:**
1. (S) Middleware: token bucket per `Fly-Client-IP` (nigdy `X-Forwarded-For`) dla tras nieuwierzytelnionych i przed-organizacyjnych; ostrzejsze wiadra dla `/v1/sso/discover` i `/v1/invitations/accept`; 429 + `Retry-After`. Magazyn: Postgres `app.rate_windows` (subject = ip) teraz, Redis później.
2. (S) Zmienić discovery SSO na `POST` z **samą domeną** (zamyka LOW-7), odpowiedź w stałym czasie i limit per IP.
3. (S) Fly: obniżyć `hard_limit`, włączyć wbudowane limity Fly; Supabase Auth: potwierdzić w runbooku limity rejestracji/resetu hasła.

### SEC-04 · Dziennik audytu bez adresu IP i bez zewnętrznych kotwic — **Wysoka (zgodność)**
**Dowód:** `AuditEvent.source_ip` nigdy nie jest wypełniane (grep `source_ip=` → brak wywołań); `audit.chain_head()` istnieje, ale nic jej nie eksportuje; ADR-0011 obiecuje kotwice w S3 Object Lock.
**Zadania:**
1. (S) Przechwytywać IP klienta (CloudFront `CloudFront-Viewer-Address` / `Fly-Client-IP`) i user agent do `TenantContext` i `emit_audit`.
2. (M) Codzienny job (pętla maintenance API lub zadanie zaplanowane) eksportujący kotwice `{tenant, seq, hash, at}` do bucketu z Object Lock (AWS) albo do Supabase Storage z polityką write-once + druga kopia mailowana/przechowywana poza platformą dla pilota; `GET /v1/audit/verify` używa kotwic (`verify_chain(anchors=…)` jest już zaimplementowane).
3. (S) Dodać partycjonowanie lub politykę archiwizacji `audit.events` (miesięczną), zanim wolumen urośnie.

### SEC-05 · Odroczone punkty z przeglądu SSO — **Średnia → Wysoka przed klientem enterprise**
**Dowód:** `DECISIONS_LOG` 2026-11-11 „SSO security review - deferred” (MEDIUM-3/4, LOW-6..9).
**Zadania:** (M) rekoncyliacja federacji Cognito po każdym deployu (start API + okresowo), (S) `auth_time` ≤ 8 h dla członków z wymuszonym SSO, (S) limit życia kluczy API (domyślnie 90 dni, max rok) i wygaszanie kluczy utworzonych przez usuniętych/SSO-wyłączonych członków, (M) osobna rola brokera z alarmem CloudTrail na `UpdateUserPoolClient`, (S) losowe nazwy providerów, (S) wymóg `amr` MFA dla break-glass właściciela i audyt każdego użycia, (S) okresowa ponowna weryfikacja TXT + lista blokowanych domen pocztowych.

### SEC-06 · Brak MFA w wariancie Supabase, MFA niewymuszone dla adminów na AWS — **Średnia**
**Dowód:** ARCHITECTURE §6 „MFA wymagane dla ról admin”; brak sprawdzeń `aal`/`amr` w `auth.py`.
**Zadania:** (M) Supabase: włączyć TOTP MFA, wymagać claimu `aal2` dla akcji `ADMIN` (`authz.require` zyskuje flagę `mfa=True` dla zarządzania członkami/kluczami/SSO/organizacją); Cognito: `MfaRequired` dla grup owner/admin, ten sam test `amr`. AC: testy na 403 `mfa-required`.

### SEC-07 · Claimy Supabase: utwardzić ścieżkę e-mail/zweryfikowany — **Niska-Średnia**
**Dowód:** `oidc_email_verified_claim = user_metadata.email_verified` (edytowalne przez użytkownika), złagodzone kontrolą userinfo; zalecany hook Custom Access Token jeszcze nie zastosowany.
**Zadania:** (S) Dodać hook Supabase Custom Access Token (serwerowe `email_verified`), przełączyć domyślną ścieżkę claimu, zachować fallback userinfo; (S) odrzucać tokeny, których `email` różni się od e-maila zapisanego w członkostwie (już zrobione dla wymuszania SSO — uogólnić).

### SEC-08 · Obsługa sekretów pilota — **Średnia**
**Dowód:** `tools/pilot-llm-setup.sh` zapisuje `LITELLM_MASTER_KEY` do `~/.mgr-ibm-llm-secrets.env`; runbook tymczasowo dopuszcza klucz główny jako klucz aplikacji; bramka potrzebuje `DATABASE_URL`.
**Zadania:** (S) generować **klucze wirtualne** per aplikacja z budżetami i usunąć plik-sejf (sekrety tylko w `fly secrets` i menedżerze haseł właściciela); (S) zrotować klucz główny po okresie przejściowym; (S) udokumentować rotację kluczy ról DB, kluczy S3 i LiteLLM w runbooku.

### SEC-09 · Brak skanu antywirusowego przed parsowaniem — **Średnia**
**Dowód:** ARCHITECTURE §10 (GuardDuty Malware Protection) odroczone (M6 M9); nic na Supabase.
**Zadania:** (M, AWS) GuardDuty Malware Protection for S3 na buckecie plików + worker czeka na tag `GuardDutyMalwareScanStatus=NO_THREATS_FOUND` (polityka bucketu odmawia `GetObject` bez niego); (M, pilot) sidecar ClamAV (`clamd`) w aplikacji parsera; pliki z wynikiem dodatnim są kwarantannowane i audytowane.

### SEC-10 · Luki łańcucha dostaw — **Średnia**
**Dowód:** obrazy bazowe po tagu (`python:3.12-slim-bookworm`, `node:22-bookworm-slim`, `litellm:v1.108.3`), nie po digest; Trivy skanuje system plików, nie zbudowane obrazy; brak cosign; CodeQL pomijany na prywatnym repo; brak SBOM dla obrazu pilota; brak bramki licencyjnej.
**Zadania:** (S) przypiąć digesty (Dependabot je aktualizuje), (S) job Trivy `image` dla trzech Dockerfile'i w `pr.yml`, (S) bramka `pip-licenses`/`license-checker` zabraniająca AGPL/SSPL (projekt już podjął decyzje licencyjne — wymusić je), (M) podpisywanie cosign keyless + weryfikacja w `deploy.sh`, (S) włączyć GitHub Advanced Security albo dodać Semgrep/Bandit jako job PR.

### SEC-11 · `/docs` i `/openapi.json` wystawione w każdym środowisku — **Niska**
**Dowód:** `create_service_app(..., docs=True)` w API; globalne CSP `default-src 'none'` i tak psuje Swagger UI.
**Zadania:** (S) `docs=settings.environment in {"local","test","dev"}`; publikować kontrakt z repozytorium (strona Redocly/Scalar w docs).

### SEC-12 · Obrona przed prompt injection jest tylko regexowa i nieewaluowana — **Średnia**
**Dowód:** `bomagent_kb/safety.py` (~8 wzorców, PL/EN); brak zbioru adwersarialnego; brak tokenów-kanarków; wolne pola tekstowe LLM (`rationale`, `message` ustaleń) renderowane w UI (React escapuje, OK).
**Zadania:** (M) korpus fixture'ów adwersarialnych (`evals/fixtures/injection/*`) z metryką „injection success rate” w `bomagent experiment`; (S) ciąg-kanarek w prompcie systemowym, którego obecność w wyjściu oznacza skompromitowane wywołanie; (S) limit rozmiaru i normalizacja unicode wolnego tekstu LLM przed zapisem; (M) opcjonalny klasyfikator LLM dla podejrzanych fragmentów (szybki model, w kontekście tenanta, UE).

### SEC-13 · Uploady i parsowanie ograniczone pamięcią na współdzielonej maszynie 2 GB — **Wysoka (pilot)**
**Dowód:** `upload_file` czyta 64 MiB do pamięci trzymając blokadę wiersza tenanta; `ProjectSize` dopuszcza 256 MiB na projekt ładowane przez workera; proces parsera `RLIMIT_AS` 1 GiB; VM Fly 2 GB dzielona z API.
**Zadania:** (M) uploady przez presigned PUT (protokół `ObjectStore` ma już `presign_put`) + wywołanie `POST …/files/complete` zapisujące sha256/rozmiar z nagłówka obiektu; (S) strumieniować multipart do pliku tymczasowego (`SpooledTemporaryFile`), jeśli upload bezpośredni zostaje; (S) ograniczyć równoległe parsowania per worker (semafor = 1) i per tenant (plan); (S) alert na OOM kill.

### SEC-14 · RODO / cykl życia danych niezaimplementowany — **Wysoka (zgodność)**
**Dowód:** brak endpointu eksportu, `DELETE /v1/projects/{id}` tylko dla przykładów, brak usuwania plików/runów/dokumentów KB, brak sweepera retencji, brak workflow offboardingu; SECURITY.md to wszystko obiecuje.
**Zadania:** (L) `POST /v1/organizations/{id}/export` (zadanie asynchroniczne → ZIP projektów, wersji BOM, dokumentów KB, dziennika audytu) oraz `DELETE /v1/organizations/{id}` (właściciel + MFA + potwierdzenie; soft-delete 30 dni, potem twarde usunięcie z obiektami, checkpointami, wierszami kolejki; końcowe zdarzenie audytu + kotwica); (M) usuwanie projektów/plików/runów/dokumentów KB z kontrolą `file-in-use`; (M) ustawienia retencji per tenant i sweep w maintenance; (S) `docs/legal/SUBPROCESSORS.md` + link w aplikacji; (S) checklista DPA dla Supabase/Fly/AWS/dostawców LLM.

### SEC-15 · Promień rażenia roli platformowej w procesie API — **Wysoka (obrona w głąb)**
**Dowód:** migracje 0001/0003: polityki `platform_onboarding` `USING (true) WITH CHECK (true)` na `tenancy.tenants` i `tenancy.memberships` dla `bomagent_platform`; API trzyma `platform_engine` do onboardingu, maintenance i (all-in-one) konsumpcji kolejek.
**Ryzyko:** RCE/SSRF w API pozwala napastnikowi wstawić członkostwo `owner` do dowolnego tenanta.
**Zadania:** (M) zastąpić bezpośrednie inserty funkcją `SECURITY DEFINER` `tenancy.create_organization(slug, name, owner_sub, email, display_name)` należącą do migratora, wykonywalną przez `bomagent_platform`, która atomowo tworzy tenanta + pierwszego właściciela i nic więcej; odebrać `INSERT` na `tenancy.memberships` roli platformowej; (S) polityka insertu platformowego do `memberships` ograniczona do tenantów bez członków; (M, AWS) dać relayowi maintenance/outbox własną minimalną rolę (tylko odczyt id tenantów) i trzymać rolę onboardingu poza kontenerami API obsługującymi ruch (osobne zadanie `onboarding` lub endpoint typu Lambda).

### SEC-16 · Hook startu sesji i automatyczne włączanie pluginów — **Niska (proces)**
**Dowód:** `.claude/settings.json` wykonuje `git merge --ff-only origin/main` przy każdym starcie sesji i włącza dwa pluginy. Nieszkodliwe (`--ff-only`), ale zaskakujące na gałęziach funkcjonalnych; udokumentować w `CLAUDE.md`.

### SEC-17 · Dodatkowe drobne punkty
- `FORWARDED_ALLOW_IPS=*` na Fly — nigdy nie opierać decyzji bezpieczeństwa na `X-Forwarded-For` (używać `Fly-Client-IP`); dodać komentarz-strażnik w `auth.py`.
- Teksty błędów parserów (`str(exc)[:500]`) trafiają do `files.summary` i do UI: upewnić się, że nie wyciekają ścieżki plików ani wnętrzności bibliotek (dodać test ze spreparowanym DXF).
- Dodać `SECURITY.md` w katalogu głównym z polityką zgłaszania podatności oraz `CODEOWNERS`; włączyć ochronę gałęzi z kontrolą `tenant isolation (blocking)` (zadanie właściciela, wymienione w HANDOFF).
- Odpowiedzi idempotencji są przechowywane wiecznie (`app.idempotency_keys` bez sweepu) — dodać TTL 24 h do pętli maintenance.

---

## 4. Ustalenia architektoniczne

### ARCH-01 · Dwa warianty wdrożenia, działa ten słabszy — **Wysoka (strategiczna)**
AWS wieloserwisowy (narracja pracy, nigdy nie wdrożony) kontra Supabase/Fly all-in-one (działający pilot, ADR-0017 „Proposed”, słabsze zabezpieczenia). Każda zmiana musi być testowana podwójnie; to na pilocie prawdziwi użytkownicy wyrobią sobie opinię.
**Rekomendacja:** zdecydować wprost. Opcja A (zalecana na najbliższe 6 miesięcy): uczynić ścieżkę Fly/Supabase pełnoprawnym „Standard tier” z utwardzeniem z SEC-01/03/13 i ARCH-02, a AWS zostawić jako roadmapę „Enterprise/silo tier”. Opcja B: wdrożyć AWS dev teraz i wygasić pilota po obronie. W obu przypadkach: jeden composition root (`bomagent_allinone` już składa serwisy) z profilami oraz macierz CI uruchamiająca ten sam zestaw E2E na obu.
**Zadania:** (S) ADR-0018 „Deployment tiers”; (S) zaakceptować/odrzucić ADR-0017; (M) job E2E na obrazie all-in-one w CI.

### ARCH-02 · Jeden proces = brak izolacji, brak skalowania poziomego — **Wysoka (pilot)**
**Zadania:** (M) grupy procesów Fly: `web` (API+SPA, 2 maszyny, rolling deploy), `worker` (konsumenci ingest/agent/kb, 1–2 maszyny, bez portu publicznego), `parser` (SEC-01), `gateway`; `release_command` zostaje; `/readyz` per grupa. AC: deploy API nie przerywa trwającego runu agenta; OOM parsera nie restartuje API.

### ARCH-03 · Maintenance O(tenantów), zapisy do DB per request, SSE na pollingu — **Średnia**
**Dowód:** `maintenance.sweep` otwiera 3 transakcje per tenant co 30 s; `hit_rate_limit` zapisuje wiersz per request; `run_events` odpytuje per klient co sekundę; kolejka Postgres odpytuje co 1 s.
**Zadania:** (S) relay outboxu: jedno zapytanie rolą platformową po oczekujących wierszach w kolejności `created_at` ze zwróconym `tenant_id`, potem dostarczanie w kontekście tenanta; (S) `LISTEN/NOTIFY` na aktualizacjach `runs.runs` i insertach do `app.queue_messages` zamiast pollingu; (M) przy > 50 tenantach lub > 100 rps: token bucket w Redis/ElastiCache (lub Fly Upstash); (S) indeks `runs.runs (tenant_id, project_id, status)` dla `refuse_if_run_active`.

### ARCH-04 · Surowy SQL w routerach; brak warstwy usług — **Średnia**
**Dowód:** 25 miejsc `noqa: S608` z f-stringowym SQL; `routers/runs.py` importuje helpery z `routers/projects.py`; reguły biznesowe żyją w routerach (kontrole limitów, audyt, outbox).
**Zadania:** (M) wprowadzić `bomagent_api/services/{projects,runs,members,kb}.py` (orkiestracja transakcji + audytu + outboxu) oraz `bomagent_api/repositories/*.py` (obiekty `Table` SQLAlchemy Core dla bezpieczeństwa kolumn w czasie kompilacji; RLS bez zmian); routery stają się cienkie. AC: brak tekstu SQL w routerach; kontrakt import-linter `routers -> services -> repositories`.

### ARCH-05 · Brak wznawiania z checkpointów; checkpointy kasowane po runie — **Średnia**
**Dowód:** `agent-worker/handler.py` usuwa wątek w `finally`; reaper oznacza runy jako nieudane po `run_timeout_s`. Duże projekty (klasa HealthyPi, > 300 linii, fan-out 8) ryzykują timeout.
**Zadania:** (M) ścieżka wznowienia: przy ponownym dostarczeniu `run.requested` dla runu `running`, którego worker padł (kolumna heartbeat), odtworzyć `Budget` z `runs.usage` i `ctx.trace`, `ainvoke(None, config)` od ostatniego checkpointu; (S) `started_at`/`heartbeat_at` zamiast stałego timeoutu 1 h; (S) `run_timeout_s` per plan.

### ARCH-06 · Snapshot KB nigdy nie tworzony dla runów z API — **Średnia (odtwarzalność)**
**Dowód:** `POST /v1/runs` nie wywołuje `KnowledgeBase.snapshot`; `kb_snapshot_id` przychodzi z payloadu jako `None`; R10 i ADR-0008 wymagają snapshotu per run.
**Zadania:** (S) tworzyć (lub reużywać ostatni niezmieniony) snapshot tenanta przy tworzeniu runu, zapisać id w wierszu, przekazać do workera; pokazać go na stronie runu i w metadanych eksportu CSV.

### ARCH-07 · Embeddingi po cichu spadają do haszowania — **Średnia**
**Dowód:** `HashingEmbeddings()`, gdy brak bramki w API i all-in-one; `/readyz` raportuje tylko `llm`.
**Zadania:** (S) `readyz_info.embeddings = fake|gateway`; odmawiać haszowania poza local/test, chyba że `BOMAGENT_ALLOW_FAKE_LLM`; baner w UI (UX-01).

### ARCH-08 · Konfiguracja bramki wypiekana w czasie builda — **Niska**
Włączenie modelu = przebudowa + redeploy bramki. Akceptowalne teraz; później: podpisana konfiguracja runtime w object storage z tą samą kontrolą `eu_guard` przy starcie bramki (`check_environment` istnieje, ale nie jest podpięte — podpiąć).

### ARCH-09 · Dryf między stanem docelowym a zbudowanym — **Średnia**
EventBridge → archiwum audytu, Langfuse, ADOT/Prometheus/Grafana, bramkowanie GuardDuty, e-mail SES, budżety LLM per tenant w bramce, wdrożenie silo: obecne na diagramach, nieobecne w kodzie. **Zadanie:** (S) dodać sekcję „As built (2026-11)” do `ARCHITECTURE.md` z tabelą „komponent → status (zaimplementowany / skonfigurowany / planowany) → ścieżka dowodu”.

### ARCH-10 · Higiena repozytorium — **Niska**
`evals/samples` to symlink do `services/api` (psuje checkouty na Windows bez trybu dewelopera i zaskakuje konteksty Dockera): zastąpić krokiem builda lub kopią package-data. Wersje modułów to wszędzie `0.1.0` bez tagów/CHANGELOG: przyjąć tagi wydań + `CHANGELOG.md` (keep-a-changelog) przed pierwszym klientem.

---

## 5. Niezawodność, operacje, dane

### OPS-01 · Brak obserwowalności na działającym pilocie — **Wysoka**
**Dowód:** `fly.toml` nie ustawia `BOMAGENT_OTEL_EXPORTER_OTLP_ENDPOINT`; Langfuse tylko w compose; brak alertów.
**Zadania:** (S) Grafana Cloud (region UE) lub własny LGTM na Fly: endpoint OTLP + nagłówek auth; (S) reguły alertów: odsetek 5xx, błędy `/readyz`, wiek kolejki > 10 min, dead letters > 0, martwe wiersze outboxu > 0, odsetek nieudanych runów, zdarzenia OOM Fly; (S) kontrola dostępności z zewnątrz (sonda UE); (S) śledzenie błędów (Sentry EU lub GlitchTip) z czyszczeniem PII.

### OPS-02 · Brak jakichkolwiek metryk (tylko ślady) — **Wysoka**
**Zadania:** (M) metryki OTel w `platform-common.telemetry`: metryki RED dla HTTP (daje je auto-instrumentacja), `bomagent_runs_total{status,variant}`, `bomagent_run_duration_s`, `bomagent_llm_tokens_total{tenant,model}`, `bomagent_llm_cost_eur_total`, głębokość/wiek kolejek, outbox pending/dead, czasy i błędy parsowania wg kodu. AC: JSON dashboardów w `deploy/observability/`.

### OPS-03 · DLQ / martwy outbox bez narzędzi — **Średnia**
**Zadania:** (S) CLI `bomagent-ops`: `outbox list|requeue|dead`, `queue dead list|requeue|purge`; (S) metryki + alarmy (OPS-02); (S) runbook „zablokowana wiadomość”.

### OPS-04 · Deploy = przestój, brak planu rollbacku — **Średnia**
**Zadania:** (S) polityka migracji expand/contract udokumentowana w `db-migrations/README.md` i egzekwowana w review (brak dropów kolumn w tym samym wydaniu); (S) rolling strategy Fly z 2 maszynami `web` po ARCH-02; (S) runbook `fly releases rollback`; (S) test smoke po deployu w CI (`tests/smoke` wobec pilota z dedykowanym tenantem smoke — zestaw istnieje, ale celuje tylko w compose).

### OPS-05 · Kopie zapasowe i DR — **Średnia**
**Zadania:** (S) płatny plan Supabase z PITR dla pilota (plan free pauzuje projekty); (M) nocny job próby odtworzenia (AWS: restore snapshotu do klastra tymczasowego, `verify_chain` i liczności wierszy; Supabase: `pg_dump` do object storage w UE + test odtworzenia); (S) RPO/RTO zapisane w runbooku.

### OPS-06 · Brakujące runbooki — **Średnia**
Reagowanie na incydenty, incydent bezpieczeństwa + notyfikacja naruszenia (72 h RODO), rotacja kluczy, odtwarzanie, offboarding tenanta, dyżury/eskalacja, pojemność. `SECURITY.md` odwołuje się do `docs/runbooks/`, który nie istnieje (faktyczny folder: `docs/platform/runbooks/`). **Zadanie:** (M) napisać je; poprawić ścieżkę.

### OPS-07 · Koszt i szybkość CI — **Niska**
Każdy push na `claude/**` uruchamia 9 jobów, w tym 3 buildy Dockera. **Zadania:** (S) filtry ścieżek, cache GHA dla uv/pnpm/warstw Dockera, `concurrency` już ustawione; (S) nocny job dla ciężkiej macierzy.

### OPS-08 · Bezpieczeństwo migracji — **Średnia**
Ręczne listy SQL, brak testów downgrade, brak lintingu czasu blokad. **Zadania:** (S) `squawk` lub `pg-safe-migrations` w CI; (S) test aplikujący wszystkie migracje, cofający jeden krok i ponownie aktualizujący; (S) `.python-version = 3.12` zgodnie z CI.

### OPS-09 · Pojemność i wydajność nieznane — **Średnia**
Brak testów k6 (TESTING.md je wymienia), brak zmierzonego p95, domyślne `concurrency=8` LangGraph bez limitu per tenant w bramce. **Zadania:** (M) scenariusze k6 (upload, run, SSE, odczyt BOM) na stosie compose co noc; (S) klucze wirtualne LiteLLM per tenant lub budżety `metadata.tenant_id` i limity równoległości; (S) opublikować notę pojemnościową (runy/godzinę per rozmiar maszyny).

### DATA-01 · Wzrost i indeksy — **Niska-Średnia**
`runs.runs.trace` i `bom.versions.content` to JSONB z całym dokumentem; `idempotency_keys` i `rate_windows` rosną; tylko indeks `runs_tenant`. **Zadania:** (S) indeksy `(tenant_id, project_id, status)` na runs i `(tenant_id, project_id)` na files; (S) sweepy TTL; (S) limity rozmiaru `trace` (zachować ostatnie N kroków lub przenieść do object storage).

### DATA-02 · Ścieżka migracji modelu embeddingów — **Niska**
Stały wymiar `vector(1024) NOT NULL`. **Zadanie:** (S) udokumentować procedurę reindeksacji; rozważyć `halfvec` i tabelę fragmentów per model przy włączeniu drugiego modelu.

---

## 6. Jakość, testy, UX, dokumentacja

### QA-01 · Stan zweryfikowany
Mocna piramida (patrz §2). Luki poniżej.

### QA-02 · Brak nagranych kaset z prawdziwych modeli — **Średnia**
`tests/cassettes` nie istnieje; `FakeChat` niczego nie odtwarza; „nagrane odpowiedzi” z TESTING.md są aspiracją. **Zadania:** (S) komenda `bomagent record` zapisująca prawdziwe odpowiedzi + usage w `tests/cassettes/<model>/`; (M) nocny job ewaluacyjny z prawdziwym modelem UE za sekretami środowiska GitHub (nigdy w CI PR), który pada na progach regresji (line F1, odsetek prób halucynacji).

### QA-03 · Testy własnościowe i mutacyjne — **Niska**
Hypothesis użyte tylko w 2 plikach; normalizacja wartości, grupowanie refdes i parsowanie CSV to idealne cele. **Zadania:** (S) strategie Hypothesis dla `values.py`, `grouping.py`, `csv_bom.py`; (S) `mutmut` na `bom-core` i `rules` raz na wydanie.

### QA-04 · Szerokość E2E — **Średnia**
5 specyfikacji na mock IdP; logowanie Supabase/społecznościowe tylko w testach jednostkowych; brak widoku mobilnego, brak regresji wizualnej. **Zadania:** (M) Playwright na obrazie all-in-one ze stubem zgodnym z Supabase (GoTrue w Dockerze) lub stubem na poziomie kontraktu; (S) projekt mobilny w `playwright.config.ts`; (S) porównanie zrzutów dla tabeli BOM, strony runu, ustawień.

### QA-05 · Brak DAST i bramek licencyjnych — **Średnia**
**Zadania:** (S) job OWASP ZAP baseline na stosie compose (co noc); (S) bramki licencyjne (SEC-10).

### UX-01 · Tryb demo jest niewidoczny — **Wysoka**
Pilot odpowiada fałszywym modelem; brak banera; BOM-y wyglądają jak prawdziwe; `readyz` pokazuje `"llm":"fake"`, ale użytkownicy tego nie czytają. **Zadania:** (S) `/config.json` zyskuje `{"mode":"demo","llm":"fake","embeddings":"fake"}`; stały górny baner PL/EN „Tryb demo — model deterministyczny, BOM-y są poglądowe”; znak wodny w nagłówku eksportu CSV i w `bom.json` (`"demo": true`); blokować lub oznaczać wyniki „Porównaj z referencją” w trybie demo.

### UX-02 · Zaproszenia bez e-maila — **Średnia**
Zapraszający musi ręcznie skopiować token. **Zadania:** (M) e-mail transakcyjny (SES eu-central-1 dla AWS; Supabase SMTP/Resend EU dla pilota) ze stroną docelową `/invite/<token>`; (S) ponowne wysłanie + wyświetlanie wygaśnięcia.

### UX-03 · Brakujące akcje cyklu życia — **Średnia**
Brak zmiany nazwy/usuwania projektu (poza przykładowymi), usuwania plików, anulowania runu, widoku historii/diffu wersji BOM, eksportu XLSX, ponownego uruchomienia z tym samym snapshotem. **Zadania:** (M) zaimplementować ze zdarzeniami audytu i kontrolą `file-in-use`; (S) lista historii wersji + diff dwóch wersji (model danych już to wspiera przez `parent_id`).

### UX-04 · Tabela BOM przy dużej skali — **Średnia**
Tylko bazowy model wierszy: brak sortowania, filtrowania, zmiany szerokości kolumn, wirtualizacji. BOM z 400 liniami z filtrem ustaleń jest już ciężki na telefonie. **Zadania:** (M) sortowanie/filtrowanie TanStack + `@tanstack/react-virtual`; (S) przyklejony nagłówek, widoczność kolumn, kopiowanie CSV.

### UX-05 · Komunikaty błędów niezlokalizowane — **Średnia**
`problemMessage()` pokazuje angielski `detail`. **Zadanie:** (S) mapować `slug` → klucz i18n z `detail` jako fallbackiem; pokryć wszystkie slugi w `locales/*.json` (test enumeruje slugi z `openapi.json`).

### UX-06 · Zarządzanie fokusem — **Niska-Średnia**
`ItemPanel` zamyka się na Esc, ale nie ma pułapki fokusu i nie zwraca fokusu do wiersza; dialogi z Radix są w porządku. **Zadanie:** (S) użyć prymitywu Dialog/Sheet z `@bomagent/ui` dla breakpointów szuflady; zwracać fokus przy zamknięciu; ogłaszać zapisaną wersję przez `aria-live`.

### UX-07 · Świadomość limitów i stany puste — **Niska**
Zużycie widzi tylko admin; brak ostrzeżenia przy 80 % runów/storage; brak checklisty pierwszego uruchomienia poza przykładami. **Zadania:** (S) chipy limitów w powłoce dla wszystkich ról (tylko do odczytu), toasty przy progach; (S) karta „pierwszy BOM w 3 krokach” na ekranie Start.

### UX-08 · Bramka regresji dostępności — **Niska**
axe działa w E2E (dobrze). Dodać `prefers-reduced-motion` i kontrole kontrastu kolorów pochodzenia w obu motywach; ustawiać `lang` na `<html>` przy ładowaniu przed pierwszym renderem (obecnie w `i18n.ts` po inicjalizacji — w porządku, zachować).

### DOC-01 · Stan docelowy a zbudowany, nakładające się pliki statusu — **Średnia**
`STATUS.md`, `HANDOFF.md`, `OWNER_CHECKLIST.md` nakładają się i dryfują (HANDOFF wciąż twierdzi, że nic nie jest zmergowane do `main`). **Zadania:** (S) `STATUS.md` = as-built + znane luki (jedno źródło), `HANDOFF.md` zarchiwizowany w `docs/history/`, `OWNER_CHECKLIST.md` jako lista zadań właściciela; (S) poprawić `README.md` „15 ADR-ów” → 17; (S) dodać sekcję „As built” do `ARCHITECTURE.md` (ARCH-09).

### DOC-02 · Dług decyzyjny — **Średnia**
~60 wierszy `DECISIONS_LOG` czeka na akceptację; kilka ma rangę architektoniczną (wariant Supabase, backend kolejki, token w SPA, model kluczy API, limity planów). **Zadania:** (S, właściciel) zaakceptować/odrzucić za jednym przejściem; (S) podnieść zaakceptowane architektoniczne do ADR-ów (ADR-0018 deployment tiers, ADR-0019 kolejka Postgres, ADR-0020 model sesji); (S) kontrola CI, w której wiersze `DECISIONS_LOG` starsze niż 60 dni z „yes” failują nocny job (widoczność, nie blokada).

### DOC-03 · Licencje i kwestie prawne — **Średnia**
Brak `LICENSE` w katalogu głównym; fixture'y CC0 z plikami SOURCE (dobrze); praca potrzebuje oświadczenia; produkt potrzebuje szkiców regulaminu/polityki prywatności/DPA. **Zadania:** (S) `LICENSE` (własnościowa „All rights reserved” lub wybrana licencja OSS — decyzja właściciela) + `NOTICE` dla fixture'ów zewnętrznych; (M) szkice dokumentów prawnych w `docs/legal/` do przeglądu przez prawnika.

### DOC-04 · Doświadczenie dewelopera — **Niska**
Cele `just` w porządku; dodać `just doctor` (sprawdza Postgres+pgvector, Node, uv), `docs/CONTRIBUTING.md`, szablon PR już istnieje; publikować OpenAPI jako statyczną stronę.

---

## 7. Praca magisterska i trafność badawcza

### TH-01 · Trafność konstrukcyjna „wariant A = 100 % LLM” — **Wysoka**
**Dowód:** `variant_a.py` używa wyjścia deterministycznego parsera (udokumentowane), `kind_of`, `package_from_footprint`, koercji Pydantic (`lines_to_items` odrzuca błędne linie), `guard_mpns` (deterministyczny filtr dowodów) w *obu* wariantach; `finish()` ponownie stosuje `guard_mpns`. `metrics.py` liczy `mpn_out_of_reference`/`unverified` na **finalnym BOM**, który strażnik już wyczyścił.
**Konsekwencja:** PB2 („odsetek halucynacji”) na finalnym BOM wynosi ~0 dla obu wariantów z konstrukcji (raport pilotażowy pokazuje 0.000 wszędzie); mierzalnym zjawiskiem jest *próba* halucynacji zapisana jako ustalenie `agent.mpn_rejected`.
**Zadania:**
1. (S) Zdefiniować w `docs/thesis/METODYKA.md` dokładny podział pracy: który kod deterministyczny dzielą oba warianty (parser, koercja schematu, strażnik MPN, metryki) i dlaczego (identyczna podłoga bezpieczeństwa dla A i B). Stwierdzić wprost, że A jest „maksymalnie LLM w ramach strzeżonego kontraktu”.
2. (S) Dodać metrykę `attempted_mpn_hallucination_rate = odrzucone decyzje MPN / wszystkie decyzje MPN` (z ustaleń) jako **główną metrykę PB2**; zachować wskaźnik na finalnym BOM jako wtórną metrykę „resztkową”; dodać obie do tabel i rysunków `experiment`.
3. (M) Opcjonalna ablacja `A-unguarded` (strażnik wyłączony, flaga w `RunConfig`) na tej samej macierzy, by zmierzyć, co strażnik usuwa — cenne dla rozdziału 7 i dla argumentu produktowego.
4. (S) Raportować pokrycie wstrzykiwanych klas błędów przez pakiet reguł (TH-06).

### TH-02 · RAG w eksperymencie różni się od produkcyjnego — **Wysoka**
**Dowód:** `cli/experiment.py` buduje `InMemoryRetriever.from_directory(config.kb_dir)` → `HashingEmbeddings` (haszowanie cech, niesemantyczne) + `LexicalReranker`. Produkcja używa pgvector + embeddingów z bramki + FTS + RRF.
**Zadania:** (M) `experiment run --retriever postgres --embedding-model <id z katalogu>` indeksujące `kb_dir` do tymczasowego tenanta przez `KnowledgeBase` i tworzące snapshot (`kb_snapshot_id` w manifeście); (S) zapisywać typ retrievera, model embeddingów i id snapshotu w `manifest.json`; (S) jeśli haszowanie zostaje ze względu na koszt, nazwać to w rozdziale 6 ograniczeniem i uruchomić co najmniej jedną konfigurację z prawdziwymi embeddingami, by pokazać wrażliwość.

### TH-03 · Rozmiar i niezależność zbioru danych — **Wysoka**
**Dowód:** 3 fixture'y KiCad + 5 projektów przykładowych, wszystkie własne i małe; `ZBIOR_EWALUACYJNY_KANDYDACI.md` wymienia prawdziwych kandydatów, ale żaden nie został wczytany; BOM-y referencyjne pochodzą z generatora.
**Zadania:** (L, właściciel + model) wczytać ≥ 6 prawdziwych otwartych projektów (BioAmp EXG Pill, Ganglion, HealthyPi Move, Card/IO, dcmini, S1 ECG; licencje + `SOURCE.md`), zbudować BOM-y referencyjne z **dwoma niezależnymi weryfikatorami** i raportować zgodność między nimi; stratyfikować wg rozmiaru (mały/średni/duży); własne projekty trzymać jako osobny zbiór „kontrolny” (pozwalają na kontrolowane wstrzykiwanie błędów) i nigdy nie łączyć ich z prawdziwymi w statystykach głównych.

### TH-04 · Doprecyzowania planu statystycznego — **Średnia**
Sparowany test permutacyjny na średnich per projekt (n = 6–8) jest uczciwy, ale słaby; 15 metryk × 2 modele to ryzyko wielokrotnych porównań. **Zadania:** (S) nota prerejestracyjna (`docs/thesis/PREREJESTRACJA.md`): metryki główne (line F1, odsetek prób halucynacji, koszt per BOM), metryki wtórne, korekta Holma dla rodziny głównej; (S) dodać analizę per linia (GEE/efekty mieszane) lub klastrowy bootstrap jako analizę wrażliwości; (S) raportować standaryzowane wielkości efektu obok surowych różnic.

### TH-05 · Modele i koszty — **Wysoka przed eksperymentem**
Koszty w katalogu to wartości zastępcze; żaden model nie jest włączony; wymiar zamknięty vs open-weight wymaga ≥ 1 modelu w każdej klasie w UE (Bedrock Claude, Mistral Large; Qwen3/gpt-oss na Bedrock EU). **Zadania:** (S) zaktualizować ceny z cenników dostawców z datą i URL źródła per wpis; (S) włączyć/zweryfikować wpisy po uzyskaniu dostępu przez właściciela; (S) zapisywać dokładne id/wersje modeli w manifeście; (S) ustalić temperaturę (0) i ziarna, udokumentować niedeterminizm modeli hostowanych.

### TH-06 · Cyrkularność eksperymentu skuteczności walidacji — **Średnia**
Wstrzykiwane klasy błędów (`drop_footprint`, `drop_mpn`, `duplicate_refdes`, `footprint_size_swap`, …) to dokładnie to, co sprawdza `core@1.0.0` → B osiąga 1.000 na fałszywym pilocie. **Zadania:** (S) dodać klasy błędów poza pokryciem reguł (błędny, lecz wiarygodny MPN, część wycofana, derating napięcia, zła tolerancja, niezgodność obudowy niewykrywalna z ciągu znaków); (S) raportować pokrycie regułami per klasa; (S) raportować fałszywe alarmy per klasa.

### TH-07 · Runtime Claude Agent SDK — **Średnia**
Testowany tylko ze skryptowanym `query`; albo uruchomić go naprawdę na Bedrock EU (i włączyć jako trzecie ramię, „agent z półki”), albo usunąć z zakresu pracy i zostawić jako pracę przyszłą.

### TH-08 · Mapowanie rozdziałów i dodatki — **Niska**
Generować Dodatek A (prompty z wersjami/haszami), Dodatek B (JSON Schema), Dodatek C (instrukcja uruchomienia) z repozytorium w czasie builda (`tools/build_docx.js` może je osadzić); dodać tabelę „pytanie badawcze → metryka → ścieżka w kodzie → test”.

### TH-09 · Raport dla opiekuna — **Niska**
`docs/supervisor/raport-postepu.pdf` istnieje; utrzymywać jednostronicowy „status eksperymentu” aktualizowany z manifestu.

---

## 8. Oceny (1–10) z uzasadnieniem

| Kategoria | Ocena | Dlaczego |
|---|---|---|
| **Całościowo jako praca magisterska** | **8** | Głębia inżynierska, narzędzia odtwarzalności (wersjonowane prompty, manifesty, statystyka) i dokumentacja znacznie przewyższają typową pracę. Obniżają: brak wyników z prawdziwych modeli, niezebrany zbiór danych, problem trafności konstrukcyjnej TH-01 i niezgodność RAG TH-02. Po domknięciu TH-01…05 to 9. |
| **Gotowość produkcyjna (SaaS)** | **5** | Fundament (tenancy, audyt, limity, outbox, IaC) jest klasy produkcyjnej; ale na ścieżce głównej nic nie jest wdrożone, pilot działa na fałszywym modelu w jednej maszynie bez obserwowalności, bez MFA, bez cyklu życia RODO, bez e-maila, bez ochrony przed nadużyciami i z ~60 niezaakceptowanymi decyzjami. |
| **Bezpieczeństwo** | **7** | Izolacja tenantów, łańcuch audytu, sandbox, strażnik UE i dyscyplina przeglądów są doskonałe. Odjęcia: model przechowywania tokenów, promień rażenia roli platformowej, brak MFA/limitów per IP/skanu antywirusowego/kotwic, odroczone punkty SSO. |
| **Użyteczność** | **6** | Czysty przepływ (upload → run → BOM z pochodzeniem → korekta → eksport → porównanie), i18n i dostępność na miejscu. Odjęcia: niewidoczny tryb demo, ręczne zaproszenia, błędy tylko po angielsku, brak sortowania/wirtualizacji tabeli, brak akcji cyklu życia. |
| **Funkcjonalność** | **7** | Oba warianty, 7 formatów, KB z korektami, SSO, klucze API, plany, porównanie A/B, ewaluacja względem referencji, runner eksperymentu. Brakuje: usuwania/eksportu, anulowania/wznawiania runu, e-maila, prawdziwych modeli, schematów PDF/Altium/DWG (udokumentowane ograniczenie). |
| **Niezawodność i odporność** | **6** | Co najmniej raz z claimami, outbox, reaper, limity. Odjęcia: jednoprocesowy pilot, brak wznawiania, przestój przy deployu, brak próby DR, brak alertów. |
| **Utrzymywalność i jakość kodu** | **8** | Ścisłe typowanie, wymuszone warstwowanie, czytelne docstringi, małe funkcje, spójne konwencje. Odjęcia: surowy SQL w routerach, kilka modułów po 500–700 linii, brak warstwy usług. |
| **Obserwowalność** | **4** | Ślady, logi strukturalne z redakcją i endpointy zdrowia istnieją w kodzie; nic nie jest podpięte na działającym pilocie; brak metryk, brak alertów, brak Langfuse w żadnej wdrożonej ścieżce. |
| **Wydajność i skalowalność** | **5** | Fan-out, structured output, haki tieringu istnieją; brak pomiarów, SSE/kolejka na pollingu, sweepy O(tenantów), rate limiting zapisem do DB, uploady ograniczone pamięcią. Wystarczające dla pilota, niesprawdzone dalej. |
| **Testowanie i QA** | **8** | 706 testów Python, w tym blokujący zestaw izolacji, testy kontraktowe, fuzzing, testy CDK, E2E + axe; progi pokrycia. Odjęcia: brak kaset/ewaluacji z prawdziwych modeli, mała szerokość E2E, brak DAST/wydajności. |
| **Dokumentacja** | **8** | Wyjątkowa objętość i jakość (ADR-y, runbooki, przewodniki właściciela, dziennik decyzji, README). Odjęcia: dryf między plikami statusu, luka docelowe-vs-zbudowane, niezaakceptowane decyzje. |
| **Trafność badawcza (eksperyment)** | **5** | Narzędzia 9/10; dowody dziś 2/10: tylko wyniki fałszywego dostawcy, haszujący RAG, własne projekty, zastępcze koszty, zerowa metryka halucynacji wymuszona strażnikiem. |
| **Zgodność i prywatność (RODO, UE, medtech)** | **5** | Wymuszenie „tylko UE” oraz audyt/pochodzenie są mocne; brakuje eksportu/usuwania/retencji, listy podprocesorów, postawy DPA, IP w audycie, kotwic, MFA. |
| **Architektura** | **7** | Architektura docelowa jest zdrowa i dobrze uzasadniona (modularny monolit + 3 workery, pooled RLS z opcją silo, bramka). Zbudowane: podwójne ścieżki wdrożenia, jednoprocesowy pilot, kilka obiecanych komponentów nieobecnych. |

---

## 9. Zalecana kolejność prac

**Faza 0 — zanim na pilocie pojawią się prawdziwe dane użytkowników (≈ 2 tygodnie)**
UX-01 baner demo · SEC-03 limity per IP · SEC-13 presigned uploady + semafor parsera · ARCH-02 grupy procesów (+ SEC-01 izolacja parsera) · OPS-01/02 endpoint OTel, metryki, alerty · SEC-04 IP źródłowe + eksport kotwic · DOC-02 akceptacja decyzji, ADR-0017/0018 · SEC-08 klucze wirtualne.

**Faza 1 — eksperyment do pracy (≈ 4–6 tygodni, równolegle z fazą 0)**
TH-05 modele + ceny · TH-02 retriever Postgres w eksperymencie · TH-01 metryka prób halucynacji + nota metodyczna · TH-03 wczytanie zbioru z podwójną weryfikacją · TH-06 dodatkowe klasy błędów · TH-04 prerejestracja · uruchomienie macierzy · rysunki do rozdziału 7.

**Faza 2 — pierwszy płacący klient pilotażowy (≈ 6–8 tygodni)**
SEC-02 sesja BFF + CSP · SEC-15 funkcja onboardingu · SEC-06 MFA · SEC-14 eksport/usuwanie/retencja · UX-02 zaproszenia e-mail · UX-03 akcje cyklu życia · SEC-09 skan antywirusowy · OPS-04/05/06 deploy, backup, runbooki · SEC-10 łańcuch dostaw · QA-02 nocne ewaluacje na prawdziwych modelach · ARCH-06 snapshoty KB per run.

**Faza 3 — skala i enterprise (drugi kwartał)**
ARCH-03 LISTEN/NOTIFY + limity w Redis · ARCH-04 warstwa usług · ARCH-05 wznawianie · SEC-05 utwardzenie SSO · AWS dev/staging/prod przez pipeline · QA-04/05 szerokość E2E + DAST + k6 · roadmapa SCIM/silo.

---

## 10. Uwagi metodyczne i ograniczenia audytu

- Przegląd statyczny repozytorium plus wykonanie zestawów lint/typy/testy jednostkowe; **brak testów dynamicznych wobec działającego pilota** (nie użyto żadnych poświadczeń, niczego nie wdrożono).
- Testy oparte na bazie (177) i stos compose/E2E nie mogły działać w tym sandboxie; w tym zakresie audyt opiera się na historii CI.
- Kod infrastruktury (`infra/cdk`) przejrzano pod kątem postawy (KMS, prywatne podsieci, polityki usuwania, reguły WAF, rola deploy OIDC), a nie linia po linii.
- Ustalenia są priorytetyzowane dla medtechowego SaaS B2B z rezydencją danych w UE; czysty prototyp badawczy ważyłby §7 wyżej, a §3–5 niżej.
