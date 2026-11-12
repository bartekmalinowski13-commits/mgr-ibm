-- Cluster-level roles. Run once per cluster by an administrator (in AWS: a CDK custom
-- resource with the master secret; locally: deploy/compose/postgres/init).
-- bomagent_migrator  owns all objects, runs migrations (separate secret)
-- bomagent_app       API and workers; NO BYPASSRLS, sees data only via RLS policies
-- bomagent_platform  platform pipelines (global knowledge base, onboarding); NO BYPASSRLS
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bomagent_migrator') THEN
        CREATE ROLE bomagent_migrator LOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bomagent_app') THEN
        CREATE ROLE bomagent_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bomagent_platform') THEN
        CREATE ROLE bomagent_platform LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;
