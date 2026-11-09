# ADR-0004: Multi-tenancy: model pooled z Postgres RLS, silo dla planu Enterprise

Status: Zaakceptowany · 2026-11-09

## Kontekst
Wiele organizacji, wymagana silna izolacja, prosty onboarding nowych klientów.

## Decyzja
Wspólna baza z kolumną `tenant_id` i Row-Level Security na każdej tabeli tenanta; `SET LOCAL app.tenant_id` w każdej transakcji; rola aplikacji bez BYPASSRLS. S3: prefiks per tenant + ABAC. Plan Enterprise: dedykowany klaster Aurora i klucz KMS, routing połączeń po `tenant_id`. Obowiązkowy zestaw testów izolacji w CI.

## Konsekwencje
Tani onboarding (rekord w bazie, nie nowa infrastruktura), obrona w głąb. Ryzyko: błąd w polityce RLS – łagodzone testami izolacji i przeglądem każdej migracji.

## Rozważane alternatywy
Schemat per tenant (problemy z migracjami przy setkach tenantów); baza per tenant dla wszystkich (koszt).
