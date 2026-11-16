import smtplib

import pytest

from bomagent_common.mailer import (
    LogMailer,
    Mail,
    MailError,
    SmtpMailer,
    invitation_mail,
    mailer_from_settings,
)


def test_default_is_log_mailer_and_smtp_needs_explicit_host():
    assert isinstance(mailer_from_settings(None), LogMailer)
    assert isinstance(mailer_from_settings(""), LogMailer)
    with pytest.raises(ValueError, match="SENDER"):
        mailer_from_settings("smtp.example.eu")  # no sender
    assert isinstance(mailer_from_settings("smtp.example.eu", sender="a@b.eu"), SmtpMailer)


async def test_log_mailer_records():
    m = LogMailer()
    mail = Mail("a@x.eu", "s", "t")
    await m.send(mail)
    assert m.sent == [mail]


def test_invitation_mail_is_bilingual_with_link():
    mail = invitation_mail(
        to="a@x.eu", org_name="Acme", inviter="Ann", link="https://app.example/invite/T", days=7
    )
    assert "https://app.example/invite/T" in mail.text
    assert "zaprasza" in mail.text
    assert "invites you" in mail.text
    assert "Zaproszenie" in mail.subject
    assert "Invitation" in mail.subject


async def test_smtp_uses_starttls_login_and_wraps_errors(monkeypatch):
    calls: list[str] = []

    class Fake:
        def __init__(self, host, port, timeout=None):
            calls.append(f"connect {host}:{port}")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            calls.append("starttls")

        def login(self, u, p):
            calls.append("login")

        def send_message(self, msg):
            calls.append(f"send {msg['To']}")

    monkeypatch.setattr(smtplib, "SMTP", Fake)
    mailer = mailer_from_settings(
        "smtp.example.eu", username="u", password="p", sender="noreply@example.eu"
    )
    await mailer.send(Mail("a@x.eu", "s", "t"))
    assert calls == ["connect smtp.example.eu:587", "starttls", "login", "send a@x.eu"]

    def boom(*a, **k):
        raise smtplib.SMTPConnectError(421, "no")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    with pytest.raises(MailError):
        await mailer.send(Mail("a@x.eu", "s", "t"))
