"""The platform-role URL of the API verifies the server certificate when a CA bundle is set."""

from sqlalchemy import make_url

from bomagent_api.app import Settings


def test_platform_url_verifies_too(monkeypatch):
    monkeypatch.setenv("BOMAGENT_DATABASE_HOST", "db.internal")
    monkeypatch.setenv("BOMAGENT_PLATFORM_DATABASE_PASSWORD", "pw")
    monkeypatch.setenv("BOMAGENT_DB_SSL_ROOT_CERT", "/etc/ssl/rds/global-bundle.pem")
    url = make_url(Settings().platform_database_url or "")
    assert url.query["sslmode"] == "verify-full"
    assert url.query["sslrootcert"] == "/etc/ssl/rds/global-bundle.pem"
