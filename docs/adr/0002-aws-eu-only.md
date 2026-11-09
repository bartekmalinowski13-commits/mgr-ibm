# ADR-0002: AWS, wyłącznie regiony UE, wiele kont

Status: Zaakceptowany · 2026-11-09

## Kontekst
Klienci to firmy medtech z UE; wymagane przetwarzanie danych w UE.

## Decyzja
AWS, region główny `eu-central-1` (Frankfurt), kopie zapasowe w `eu-west-1`. AWS Organizations z kontami: management, security, log-archive, shared-services, dev, staging, prod. SCP odmawia akcji w regionach spoza UE (wyjątki dla usług globalnych: IAM, CloudFront, Route 53, Organizations).

## Konsekwencje
Silna izolacja środowisk i jasny dowód rezydencji danych dla klientów. Koszt: więcej kont do zarządzania (Control Tower / IaC).

## Rozważane alternatywy
Jedno konto z tagami (słaba izolacja, trudny audyt); inny chmurowy dostawca (brak przewagi, Bedrock daje dostęp do Claude w UE).
