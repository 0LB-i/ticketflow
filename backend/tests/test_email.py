"""Envio de e-mail por SMTP e o modo sem SMTP (questão 1)."""

import smtplib
from email.message import EmailMessage
from typing import Any

import pytest

from chamados.config import Settings
from chamados.modules.notifications.email import LogMailer, SmtpMailer, make_mailer


class SmtpFalso:
    instancias: list["SmtpFalso"] = []  # noqa: RUF012

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host, self.port = host, port
        self.chamadas: list[Any] = []
        SmtpFalso.instancias.append(self)

    def __enter__(self) -> "SmtpFalso":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def starttls(self) -> None:
        self.chamadas.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.chamadas.append(("login", user))

    def send_message(self, msg: EmailMessage) -> None:
        self.chamadas.append(msg)


def test_escolhe_o_envio_pela_configuracao() -> None:
    assert isinstance(make_mailer(Settings(smtp_host="")), LogMailer)
    assert isinstance(make_mailer(Settings(smtp_host="smtp.exemplo.com")), SmtpMailer)


def test_smtp_envia_com_starttls_e_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", SmtpFalso)
    s = Settings(smtp_host="smtp.exemplo.com", smtp_user="ticketflow", smtp_from="TF <tf@x.com>")
    SmtpMailer(s).send("ana@exemplo.com", "Assunto", "Corpo")
    smtp = SmtpFalso.instancias[-1]
    assert (smtp.host, smtp.port) == ("smtp.exemplo.com", 587)
    assert smtp.chamadas[:2] == ["starttls", ("login", "ticketflow")]
    msg = smtp.chamadas[2]
    assert msg["To"] == "ana@exemplo.com" and msg["From"] == "TF <tf@x.com>"
    assert msg.get_content().strip() == "Corpo"


def test_falha_de_smtp_nao_derruba_a_requisicao(monkeypatch: pytest.MonkeyPatch) -> None:
    def recusa(*_: object, **__: object) -> None:
        raise ConnectionRefusedError

    monkeypatch.setattr(smtplib, "SMTP", recusa)
    SmtpMailer(Settings(smtp_host="smtp.exemplo.com")).send("a@b.com", "x", "y")


def test_sem_smtp_vai_para_o_log() -> None:
    LogMailer().send("a@b.com", "Assunto", "Corpo")
