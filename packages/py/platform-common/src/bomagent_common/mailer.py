"""Transactional e-mail (audit UX-02).

``Mailer`` is a small protocol. ``LogMailer`` (default; local and tests) records messages in
memory and logs only the recipient domain and subject - never the body, which carries a
single-use secret. ``SmtpMailer`` talks to an SMTP relay chosen by the operator: there is no
default host, and no mail leaves the platform unless ``BOMAGENT_SMTP_HOST`` is set (EU
processing is the operator's responsibility, ADR-0002). The relay connection always uses TLS.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from bomagent_common.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str


class MailError(RuntimeError):
    """The message could not be handed to the relay."""


class Mailer(Protocol):
    async def send(self, mail: Mail) -> None: ...


@dataclass
class LogMailer:
    """Keeps messages in ``sent`` (tests, local dev). Never logs the body."""

    sent: list[Mail] = field(default_factory=list)

    async def send(self, mail: Mail) -> None:
        self.sent.append(mail)
        log.info("mail.logged", to_domain=mail.to.rpartition("@")[2], subject=mail.subject)


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int = 587
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    sender: str = ""
    implicit_tls: bool = False  # True: SMTPS (port 465); False: STARTTLS (port 587)
    timeout_s: float = 10.0


class SmtpMailer:
    def __init__(self, config: SmtpConfig) -> None:
        if not config.host or not config.sender:
            raise ValueError("SMTP host and sender are required")
        self._c = config

    def _deliver(self, mail: Mail) -> None:
        c = self._c
        msg = EmailMessage()
        msg["From"] = c.sender
        msg["To"] = mail.to
        msg["Subject"] = mail.subject
        msg.set_content(mail.text)
        ctx = ssl.create_default_context()
        try:
            if c.implicit_tls:
                with smtplib.SMTP_SSL(c.host, c.port, timeout=c.timeout_s, context=ctx) as s:
                    self._send(s, msg)
            else:
                with smtplib.SMTP(c.host, c.port, timeout=c.timeout_s) as s:
                    s.starttls(context=ctx)
                    self._send(s, msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailError(type(exc).__name__) from exc

    def _send(self, s: smtplib.SMTP, msg: EmailMessage) -> None:
        if self._c.username and self._c.password:
            s.login(self._c.username, self._c.password)
        s.send_message(msg)

    async def send(self, mail: Mail) -> None:
        await asyncio.to_thread(self._deliver, mail)


def mailer_from_settings(
    host: str | None,
    *,
    port: int = 587,
    username: str | None = None,
    password: str | None = None,
    sender: str | None = None,
    implicit_tls: bool = False,
) -> Mailer:
    """SMTP only when a host is configured; otherwise the in-memory/log mailer."""
    if not host:
        return LogMailer()
    if not sender:
        raise ValueError("BOMAGENT_SMTP_SENDER is required when BOMAGENT_SMTP_HOST is set")
    return SmtpMailer(SmtpConfig(host, port, username, password, sender, implicit_tls))


def invitation_mail(*, to: str, org_name: str, inviter: str, link: str, days: int) -> Mail:
    """Bilingual (PL + EN) invitation; the invitee's language is not known before sign-up."""
    pl = (
        f"{inviter} zaprasza Cię do organizacji „{org_name}” w BOM Agent.\n\n"
        f"Aby dołączyć, otwórz link (ważny {days} dni, jednorazowy) i zaloguj się tym adresem "
        f"e-mail ({to}):\n{link}\n\n"
        "Jeśli to nie dotyczy Ciebie, zignoruj tę wiadomość."
    )
    en = (
        f'{inviter} invites you to the organisation "{org_name}" in BOM Agent.\n\n'
        f"To join, open the link (single use, valid for {days} days) and sign in with this "
        f"e-mail address ({to}):\n{link}\n\n"
        "If this is not meant for you, ignore this message."
    )
    return Mail(
        to=to,
        subject=f"Zaproszenie do {org_name} / Invitation to {org_name} - BOM Agent",
        text=f"{pl}\n\n--\n\n{en}\n",
    )
