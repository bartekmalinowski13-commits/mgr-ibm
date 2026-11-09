# ADR-0016: Jeden pakiet migracji z ręcznie pisanym DDL i rolami bazy

Status: Zaakceptowany · 2026-11-09 (decyzja agenta, do akceptacji – patrz `docs/DECISIONS_LOG.md`)

## Kontekst
Cztery serwisy korzystają z jednej bazy Aurora PostgreSQL (ADR-0004). Każda tabela tenanta wymaga polityk RLS, a każda migracja zmieniająca polityki – przeglądu bezpieczeństwa (SECURITY.md). Autogenerowane migracje nie znają polityk RLS ani uprawnień ról.

## Decyzja
- Pakiet `packages/py/db-migrations` (`bomagent_migrations`, warstwa fundamentu) zawiera **całe** DDL platformy jako ręcznie pisane migracje Alembic; moduły domenowe trzymają tylko definicje tabel do zapytań.
- Role klastra (`bootstrap.sql`): `bomagent_migrator` (właściciel obiektów, migracje), `bomagent_app` (API i workery), `bomagent_platform` (potoki platformy: globalna KB, onboarding). Żadna nie ma `BYPASSRLS` ani `SUPERUSER`.
- Każda tabela tenanta: `ENABLE` + `FORCE ROW LEVEL SECURITY`, polityki oparte o `app.current_tenant_id()` (NULL bez kontekstu ⇒ brak wierszy). Test katalogowy w zestawie `isolation` pilnuje, że nowa tabela z `tenant_id` nie przejdzie bez RLS.
- Migracje uruchamia osobne zadanie (ECS one-off / `migrate` w compose) z sekretem migratora.

## Konsekwencje
Jedno miejsce przeglądu polityk; migracje są kodem z testami. Koszt: brak autogeneracji – zmiany tabel wymagają ręcznego DDL.

## Rozważane alternatywy
Migracje per serwis (konflikty kolejności, rozproszone polityki); autogenerate z SQLAlchemy (brak RLS i grantów).
