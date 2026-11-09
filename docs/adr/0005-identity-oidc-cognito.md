# ADR-0005: Tożsamość: OIDC, Amazon Cognito, SSO per organizacja

Status: Zaakceptowany · 2026-11-09

## Kontekst
Klienci B2B oczekują SSO (SAML/OIDC), MFA i ról.

## Decyzja
Cognito w `eu-central-1` z federacją SAML 2.0 / OIDC konfigurowaną per organizacja; aplikacja zależy tylko od standardu OIDC (JWT). RBAC: owner, admin, engineer, reviewer, viewer; polityki w module `authz` w stylu Cedar. Klucze API per organizacja. SCIM – osobny ADR przy pierwszym kliencie Enterprise.

## Konsekwencje
Dane tożsamości w UE, zarządzana usługa. Ograniczenie: Cognito nie ma SCIM – dlatego zależność tylko od OIDC, żeby można było przejść na Keycloak.

## Rozważane alternatywy
Keycloak self-hosted (pełna kontrola, ale operacje i aktualizacje bezpieczeństwa po naszej stronie); Auth0/Clerk/WorkOS (świetne DX, ale dodatkowy podprocesor danych i kwestia rezydencji).
