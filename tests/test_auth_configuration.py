from __future__ import annotations

import logging

import pytest

from orl_web.config import Settings
from orl_web.delivery import ResearchEmail
from orl_web.email import ConsoleMailer, SMTPMailer, default_mailer


@pytest.mark.spec("WEB-AUTH-001")
def test_console_mailer_logs_development_link(caplog):
    with caplog.at_level(logging.WARNING, logger="orl_web.auth"):
        ConsoleMailer().send("person@example.org", "http://localhost/auth/verify?token=secret")
    assert "person@example.org" in caplog.text and "token=secret" in caplog.text
    assert isinstance(default_mailer(Settings()), ConsoleMailer)


@pytest.mark.spec("WEB-ACCESS-003", "WEB-MAIL-002")
def test_console_mailer_logs_development_access_approval_and_research(caplog):
    with caplog.at_level(logging.WARNING, logger="orl_web.auth"):
        ConsoleMailer().send_access_approved("member@example.org", "http://localhost/login",
                                             "http://localhost/unsubscribe/u/sig")
        ConsoleMailer().send_research("member@example.org", ResearchEmail(
            subject="New on TruthLM: A question", text="Body", html="<p>Body</p>",
            unsubscribe_url="http://localhost/unsubscribe/u/sig"))
    assert "member@example.org" in caplog.text and "http://localhost/login" in caplog.text
    assert "New on TruthLM: A question" in caplog.text


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
            body = message.get_body(("plain",)).get_content()
            calls.append(("send", message["To"], message["From"], body, message))

    monkeypatch.setattr("orl_web.email.smtplib.SMTP", FakeSMTP)
    settings = Settings(email_delivery="smtp", smtp_host="smtp.example.org", smtp_port=2525,
                        smtp_username="user", smtp_password="pass",
                        smtp_from_email="TruthLM <research@example.org>")
    assert isinstance(default_mailer(settings), SMTPMailer)
    SMTPMailer(settings).send("person@example.org", "https://truthlm.com/auth/verify?token=abc")
    assert calls[0] == ("connect", "smtp.example.org", 2525, 15)
    assert ("starttls",) in calls and ("login", "user", "pass") in calls
    assert calls[-1][0:3] == ("send", "person@example.org", "TruthLM <research@example.org>")
    SMTPMailer(settings).send_access_approved("member@example.org", "https://truthlm.com/login",
                                              "https://truthlm.com/unsubscribe/u/sig")
    assert calls[-1][0:3] == ("send", "member@example.org", "TruthLM <research@example.org>")
    welcome = calls[-1][3]
    assert "https://truthlm.com/login" in welcome and "subscription is active" in welcome
    assert "https://truthlm.com/unsubscribe/u/sig" in welcome
    assert "paid" not in welcome.lower() and "upvote" not in welcome.lower()
    assert calls[-1][4]["List-Unsubscribe"] == "<https://truthlm.com/unsubscribe/u/sig>"


@pytest.mark.spec("WEB-MAIL-004")
def test_smtp_research_email_has_text_html_and_one_click_unsubscribe(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def starttls(self):
            pass

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("orl_web.email.smtplib.SMTP", FakeSMTP)
    settings = Settings(email_delivery="smtp", smtp_host="smtp.example.org",
                        smtp_from_email="TruthLM <research@example.org>")
    SMTPMailer(settings).send_research("reader@example.org", ResearchEmail(
        subject="New on TruthLM: Does the effect hold?", text="Plain body",
        html="<p>HTML body</p>", unsubscribe_url="https://truthlm.com/unsubscribe/u/sig"))
    message = sent[0]
    assert message["To"] == "reader@example.org" and message["Subject"].startswith("New on TruthLM")
    assert message["List-Unsubscribe"] == "<https://truthlm.com/unsubscribe/u/sig>"
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert message.get_body(("plain",)).get_content().strip() == "Plain body"
    assert message.get_body(("html",)).get_content().strip() == "<p>HTML body</p>"


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
