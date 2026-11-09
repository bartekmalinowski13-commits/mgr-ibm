# Bezpieczeństwo, prywatność, zgodność

Cel: poziom gotowy do audytu u klienta medtech. Docelowo **OWASP ASVS poziom 2** dla aplikacji, kontrolki gotowe pod ISO/IEC 27001 / SOC 2, wsparcie identyfikowalności klientów działających w ISO 13485.

## Pozycja regulacyjna (do potwierdzenia z doradcą)
Platforma jest narzędziem wspomagającym projektowanie (inżynieria), a nie oprogramowaniem przeznaczonym do diagnozy lub terapii – najpewniej **nie jest wyrobem medycznym** w rozumieniu MDR 2017/745. Klienci jednak używają jej w procesie projektowym objętym ISO 13485, więc dostarczamy: log audytu, pochodzenie każdej pozycji BOM, wersjonowanie, eksport dowodów. Ewentualna walidacja narzędzia po stronie klienta (ISO 13485 §4.1.6) – dokumentacja walidacyjna jako przyszły produkt.

## RODO
- Przetwarzanie i przechowywanie wyłącznie w UE (ADR-0002, ADR-0006).
- Rola: procesor dla danych klientów; umowa DPA; publiczna lista podprocesorów (AWS; Microsoft – Azure OpenAI; Mistral; – każdy z przetwarzaniem w UE).
- Minimalizacja: dane osobowe tylko użytkowników (imię, e-mail, logi dostępu). Pliki projektowe to tajemnica przedsiębiorstwa klienta – traktowane jak dane najwyższej poufności.
- Retencja konfigurowalna per organizacja; eksport i trwałe usunięcie danych organizacji (offboarding) z potwierdzeniem w logu audytu.

## Model zagrożeń (skrót, STRIDE)
| Zagrożenie | Kontrola |
|---|---|
| Dostęp do danych innej organizacji | RLS + kontekst tenanta + ABAC S3 + testy izolacji w CI (blokują merge) |
| Złośliwy plik (zip bomb, XXE, exploit parsera) | skan malware, limity rozmiaru/czasu, parser w izolowanym zadaniu bez sieci, non-root, read-only FS, bezpieczne parsery XML (defusedxml) |
| Prompt injection z plików/datasheetów | treść dokumentów zawsze jako dane (oddzielone od instrukcji), narzędzia agentów z minimalnymi uprawnieniami i tylko w kontekście tenanta, wyjście LLM walidowane schematem, agent nie wykonuje kodu ani nie robi żądań sieciowych |
| Wyciek danych do dostawcy LLM spoza UE | tylko LLM Gateway, allowlista egress, katalog modeli z atrybutem rezydencji, testy konfiguracji |
| Przejęcie konta | SSO, MFA dla adminów, krótkie tokeny, odświeżanie z rotacją, wykrywanie anomalii logowania (Cognito advanced security) |
| Nadużycie kosztów (LLM) | budżety i limity per tenant i per przebieg, rate limiting |
| Podmiana zależności / obrazu | lockfile, Renovate/Dependabot, Trivy, SBOM (Syft), podpis obrazów (cosign), akcje GitHub przypięte do SHA |
| Wyciek sekretów | Secrets Manager, gitleaks w CI i pre-commit, brak sekretów w logach (filtry) |
| Manipulacja logiem audytu | append-only + hash chain + S3 Object Lock w osobnym koncie log-archive |

## Infrastruktura
WAF (zestawy AWS Managed Rules + rate limiting) na CloudFront; TLS 1.2+ wszędzie; szyfrowanie w spoczynku KMS (Aurora, S3, SQS, logi); bazy w podsieciach prywatnych; VPC endpoints; GuardDuty (w tym Malware Protection for S3 i Runtime Monitoring dla ECS), Security Hub (AWS FSBP, CIS), AWS Config, IAM Access Analyzer, CloudTrail organizacji; SCP: regiony tylko UE, zakaz wyłączania CloudTrail/GuardDuty, zakaz publicznych bucketów.

## Aplikacja
Walidacja wejścia (Pydantic), CSP i nagłówki bezpieczeństwa, ochrona CSRF dla sesji cookie, CORS tylko dla własnych domen, limity zapytań per tenant i klucz API, idempotencja, brak treści plików i promptów w logach aplikacyjnych (w Langfuse tylko w przestrzeni tenanta i z retencją), skan DAST (OWASP ZAP baseline) na stagingu.

## Procesy
Przegląd bezpieczeństwa każdej migracji zmieniającej polityki RLS; kwartalny przegląd uprawnień; plan reakcji na incydenty (runbook w `docs/runbooks/`); testy penetracyjne przed pierwszym klientem produkcyjnym.
