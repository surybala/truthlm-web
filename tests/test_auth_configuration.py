from __future__ import annotations

import logging

import pytest

from orl_web.config import Settings
from orl_web.email import ConsoleMailer, SMTPMailer, default_mailer


@pytest.mark.spec("WEB-AUTH-001")
def test_console_mailer_logs_development_link(caplog):
    with caplog.at_level(logging.WARNING, logger="orl_web.auth"):
        ConsoleMailer().send("person@example.org", "http://localhost/auth/verify?token=secret")
    assert "person@example.org" in caplog.text and "token=secret" in caplog.text
    assert isinstance(default_mailer(Settings()), ConsoleMailer)


@pytest.mark.spec("WEB-ACCESS-003")
def test_console_mailer_logs_development_access_approval(caplog):
    with caplog.at_level(logging.WARNING, logger="orl_web.auth"):
        ConsoleMailer().send_access_approved("member@example.org", "http://localhost/login")
    assert "member@example.org" in caplog.text and "http://localhost/login" in caplog.text


@pytest.mark.spec("WEB-AUTH-001")
def test_smtp_mailer_uses_tls_and_credentials(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def starttls(self):
            calls.append(("starttls",))

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message):
            calls.append(("send", message["To"], message["From"], message.get_content()))

    monkeypatch.setattr("orl_web.email.smtplib.SMTP", FakeSMTP)
    settings = Settings(email_delivery="smtp", smtp_host="smtp.example.org", smtp_port=2525,
                        smtp_username="user", smtp_password="pass",
                        smtp_from_email="TruthLM <research@example.org>")
    assert isinstance(default_mailer(settings), SMTPMailer)
    SMTPMailer(settings).send("person@example.org", "https://truthlm.com/auth/verify?token=abc")
    assert calls[0] == ("connect", "smtp.example.org", 2525, 15)
    assert ("starttls",) in calls and ("login", "user", "pass") in calls
    assert calls[-1][0:3] == ("send", "person@example.org", "TruthLM <research@example.org>")
    SMTPMailer(settings).send_access_approved("member@example.org", "https://truthlm.com/login")
    assert calls[-1][0:3] == ("send", "member@example.org", "TruthLM <research@example.org>")
    assert "https://truthlm.com/login" in calls[-1][3] and "early access" in calls[-1][3]


def test_production_auth_configuration_is_strict():
    base = {"environment": "production", "database_url": "postgresql+psycopg://db",
            "jwt_secret": "x" * 40, "email_delivery": "smtp",
            "smtp_host": "smtp.example.org", "smtp_from_email": "mail@example.org"}
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(**base).validate()
    with pytest.raises(ValueError, match="SMTP"):
        Settings(**{**base, "base_url": "https://truthlm.com", "smtp_host": ""}).validate()
    Settings(**{**base, "base_url": "https://truthlm.com"}).validate()
    with pytest.raises(ValueError, match="authentication lifetimes"):
        Settings(session_days=0).validate()
    with pytest.raises(ValueError, match="email delivery"):
        Settings(email_delivery="invalid").validate()
