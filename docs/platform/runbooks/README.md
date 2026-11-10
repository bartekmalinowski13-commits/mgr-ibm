# Runbooki operacyjne

Wszystkie operacje na chmurze wykonuje **człowiek** (lub pipeline uruchomiony przez człowieka) – nigdy sesja Claude Code (CLAUDE.md §6).

## first-deployment – pierwsze wdrożenie środowiska
1. **Konta (AWS Organizations):** management, security, log-archive, shared-services, dev, staging, prod. Zastosuj SCP z `infra/cdk/policies/` (najpierw w trybie testowym na OU dev).
2. **shared-services:** repozytoria ECR `bomagent-api`, `bomagent-ingest-worker`, `bomagent-agent-worker`, `bomagent-kb-indexer`, `bomagent-migrate`, `bomagent-llm-gateway` (skan przy pushu, niezmienne tagi, polityka pull dla kont dev/staging/prod) oraz rola OIDC dla GitHub (`vars.AWS_IMAGES_ROLE_ARN`) z prawem pushu tylko do tych repozytoriów.
3. **Konto środowiska:** `cdk bootstrap aws://<konto>/eu-central-1 aws://<konto>/us-east-1 aws://<konto>/eu-west-1`, potem jednorazowo z laptopa administratora: `pnpm --filter @bomagent/infra exec cdk deploy BomAgent-<env>-Cicd -c bomagent:env=<env> -c bomagent:account=<konto> -c bomagent:githubRepository=<owner>/<repo>`.
4. **GitHub:** środowiska `images`, `dev`, `staging`, `prod` (prod: wymagane zatwierdzenie). Zmienne: `AWS_DEPLOY_ROLE_ARN` (z wyjścia stacku Cicd), `AWS_ACCOUNT_ID`, `IMAGE_REGISTRY`, opcjonalnie `DOMAIN_NAME`; na końcu `AWS_DEPLOY_ENABLED=true`.
5. **Bedrock:** w konsoli Bedrock (eu-central-1) włącz dostęp do modeli z katalogu; w `packages/py/llm/src/bomagent_llm/catalog/models.yaml` ustaw `enabled: true` i `verified: true` dopiero po sprawdzeniu, że model działa przez profil EU.
6. **Push na `main`** uruchamia `main.yml`: obrazy → `tools/deploy.sh` dla dev → staging → prod (cdk deploy, migracje, publikacja SPA z `config.json`, smoke). Przy pierwszym wdrożeniu bez domeny skrypt drugi raz wdraża stack Identity z adresem CloudFront (callback Cognito).
7. **Baza – pierwszy raz:** zadanie migracji wykonuje `bomagent-migrate upgrade`; role `bomagent_app`/`bomagent_platform` dostają hasła z sekretów stacku Data przez `bomagent-migrate bootstrap` uruchomione raz tym samym zadaniem z nadpisaną komendą.
8. **Pierwszy administrator:** zarejestruj się w aplikacji (weryfikacja e-maila), załóż organizację; hasło ustawiasz sam – nikomu go nie przekazujesz.

## rotate-db-role-passwords
Wygeneruj nowe hasło w sekrecie roli (Secrets Manager „Rotate immediately” nie działa dla ról bez funkcji rotacji), uruchom zadanie migracji z komendą `bomagent-migrate bootstrap` (ustawia hasła ról z sekretów), następnie wymuś nowe wdrożenie serwisów ECS (`aws ecs update-service --force-new-deployment`).

## rotate-internal-secrets
Klucz bramki LLM i nagłówek `X-Origin-Verify`: zmień wartość sekretu, wdroż ponownie stacki Compute i Edge (CloudFront dostaje nową wartość nagłówka), potem wymuś nowe wdrożenie serwisów.

## incident: wiadomości w DLQ
Alarm `*DlqAlarm`: sprawdź logi workera (`/bomagent/<env>/<worker>`), napraw przyczynę, przenieś wiadomości z DLQ do kolejki („Start DLQ redrive”). Przebiegi zawieszone > `run_timeout_s` reaper w API oznaczy jako `failed`.
