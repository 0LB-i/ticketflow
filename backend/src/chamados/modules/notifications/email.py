"""Envio de e-mail. Sem SMTP configurado, a mensagem vai para o log (desenvolvimento e
instalações que ainda não definiram o provedor, questão 1)."""

import smtplib
from email.message import EmailMessage
from typing import Protocol

import structlog

from chamados.config import Settings

log = structlog.get_logger(__name__)


class Mailer(Protocol):
    configured: bool

    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    configured = True

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as smtp:
                if self.s.smtp_starttls:
                    smtp.starttls()
                if self.s.smtp_user:
                    smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(msg)
            log.info("email_enviado", to=to, subject=subject)
        except (OSError, smtplib.SMTPException):
            log.exception("email_falhou", to=to, subject=subject)


class LogMailer:
    configured = False

    def send(self, to: str, subject: str, body: str) -> None:
        log.warning("email_sem_smtp", to=to, subject=subject, body=body)


def make_mailer(settings: Settings) -> Mailer:
    return SmtpMailer(settings) if settings.smtp_host else LogMailer()
