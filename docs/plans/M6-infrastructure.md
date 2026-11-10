# M6 – Infrastruktura (`infra/cdk`)

Zasada nadrzędna (CLAUDE.md §6): **kod + `cdk synth` + testy**. Żadnego `cdk deploy`, żadnych zasobów w chmurze z sesji Claude Code. Wdrożenie uruchamia człowiek z pipeline'u (joby wyłączone do `vars.AWS_DEPLOY_ENABLED == 'true'`).

## Brainstorming (pytania → odpowiedzi z dokumentów)
| Pytanie | Odpowiedź | Źródło |
|---|---|---|
| Narzędzie | AWS CDK v2 (TypeScript) + cdk-nag (AwsSolutions, HIPAA Security jako punkt odniesienia) | ADR-0013, ARCHITECTURE §12 |
| Stacki | network, data, identity, compute, observability, edge, security-baseline (+ cicd: rola GitHub OIDC) | ADR-0013, ARCHITECTURE §13 |
| Region | `eu-central-1`; kopie AWS Backup do `eu-west-1`; WAF dla CloudFront musi powstać w `us-east-1` (usługa globalna – wyjątek dopuszczony w ADR-0002) | ADR-0002, ARCHITECTURE §12 |
| Konta | Organizations (management, security, log-archive, shared-services, dev/staging/prod) zakłada człowiek; repo zawiera tylko polityki SCP (`infra/cdk/policies/`) do zastosowania i stacki obciążeniowe dla kont dev/staging/prod | ARCHITECTURE §12 |
| Synth bez poświadczeń | żadnych `fromLookup`; konto i parametry z kontekstu (`cdk.json`, zmienne CI) z kontem-zaślepką `000000000000` w synth | CLAUDE.md §6 |
| Baza | Aurora PostgreSQL 16 Serverless v2, szyfrowanie KMS, podsieci izolowane, IAM auth, Performance Insights z KMS, backtrack niedostępny dla PG – PITR + AWS Backup | ADR-0004, ADR-0008 |
| Kolejki | SQS ingest/runs/kb + DLQ (maxReceiveCount 5), SSE-KMS, polityka TLS-only | ADR-0003 |
| Parsery | ingest-worker w podsieci izolowanej (bez NAT), tylko VPC endpoints S3/SQS/Logs/ECR; read-only root FS, non-root | ADR-0009, CLAUDE.md §5 |
| LLM | LiteLLM jako serwis ECS z endpointem VPC do Bedrock; wyjście do Azure OpenAI EU / Mistral przez NAT (allowlista domen – Network Firewall jako opcja, poza zakresem v1 – patrz DECISIONS_LOG) | ADR-0006 |
| API za CloudFront | ALB w podsieciach publicznych, ruch tylko z CloudFront (zarządzana lista prefiksów przekazana parametrem – bez lookupów) + nagłówek-sekret origin; WAF (AWS Managed Rules + rate limit) na CloudFront | SECURITY.md |
| SPA | S3 prywatny + OAC, nagłówki bezpieczeństwa (CSP, HSTS) przez Response Headers Policy | UX/SECURITY |
| Logowanie | Cognito User Pool (weryfikacja e-maila, MFA TOTP opcjonalne → wymagane dla adminów w aplikacji, threat protection), klient SPA bez sekretu z PKCE (authorization code), domena Hosted UI | ADR-0005 |
| Obserwowalność | grupy logów z KMS i retencją, alarmy (DLQ > 0, 5xx ALB, CPU, wiek wiadomości), SNS | ADR-0010 |
| Bezpieczeństwo konta | GuardDuty (S3 Malware Protection, Runtime Monitoring ECS), Security Hub (FSBP, CIS), IAM Access Analyzer, CloudTrail konta jeśli brak organizacyjnego (flaga) | SECURITY.md |

## Plan zadań
1. Szkielet `infra/cdk` (pakiet `@bomagent/infra`, konfiguracja środowisk, aspekty: cdk-nag + tagi), test „synth wszystkich stacków bez błędów cdk-nag”.
2. network → data → identity → compute → edge (+ waf w us-east-1) → observability → security-baseline → cicd; dla każdego: testy asercji (najważniejsze własności bezpieczeństwa), potem kod.
3. `policies/scp-*.json` (tylko UE, zakaz wyłączania CloudTrail/GuardDuty, zakaz publicznych bucketów).
4. Logowanie Cognito (PKCE) w `apps/web` (konfiguracja z `/config.json` generowanego przy wdrożeniu).
5. `just synth`, CI (job `cdk`), runbooki w `docs/platform/runbooks/`.
