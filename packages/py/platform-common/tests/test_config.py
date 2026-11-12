def test_database_url_is_composed_from_parts_with_tls(monkeypatch):
    from bomagent_common.config import ServiceSettings

    monkeypatch.setenv("BOMAGENT_DATABASE_HOST", "db.cluster.eu-central-1.rds.amazonaws.com")
    monkeypatch.setenv("BOMAGENT_DATABASE_PASSWORD", "p@ss/word")
    settings = ServiceSettings()
    assert settings.database_url == (
        "postgresql+psycopg://bomagent_app:p%40ss%2Fword@"
        "db.cluster.eu-central-1.rds.amazonaws.com:5432/bomagent?sslmode=require"
    )


def test_explicit_database_url_wins(monkeypatch):
    from bomagent_common.config import ServiceSettings

    monkeypatch.setenv("BOMAGENT_DATABASE_URL", "postgresql+psycopg://u:p@h/d")
    monkeypatch.setenv("BOMAGENT_DATABASE_HOST", "ignored")
    monkeypatch.setenv("BOMAGENT_DATABASE_PASSWORD", "ignored")
    assert ServiceSettings().database_url == "postgresql+psycopg://u:p@h/d"


def test_ssl_root_cert_switches_the_composed_url_to_verify_full(monkeypatch):
    from sqlalchemy import make_url

    from bomagent_common.config import ServiceSettings

    monkeypatch.setenv("BOMAGENT_DATABASE_HOST", "db.cluster.eu-central-1.rds.amazonaws.com")
    monkeypatch.setenv("BOMAGENT_DATABASE_PASSWORD", "pw")
    monkeypatch.setenv("BOMAGENT_DB_SSL_ROOT_CERT", "/etc/ssl/rds/global-bundle.pem")
    url = make_url(ServiceSettings().database_url or "")
    assert url.query["sslmode"] == "verify-full"
    assert url.query["sslrootcert"] == "/etc/ssl/rds/global-bundle.pem"


def test_no_ssl_root_cert_keeps_sslmode_require():
    from bomagent_common.config import postgres_url

    assert postgres_url("u", "p", "h", 5432, "d").endswith("?sslmode=require")
