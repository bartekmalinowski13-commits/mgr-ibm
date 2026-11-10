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
