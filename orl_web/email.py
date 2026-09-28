"""Sign-in link and membership notice delivery adapters."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from .config import Settings


class Mailer(Protocol):
    def send(self, email: str, verify_url: str) -> None: ...

    def send_access_approved(self, email: str, sign_in_url: str) -> None: ...


class ConsoleMailer:
    def send(self, email: str, verify_url: str) -> None:
        logging.getLogger("orl_web.auth").warning("Development sign-in link for %s: %s", email,
                                                  verify_url)

    def send_access_approved(self, email: str, sign_in_url: str) -> None:
        logging.getLogger("orl_web.auth").warning("Development access approval for %s: %s", email,
                                                  sign_in_url)


class SMTPMailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, email: str, verify_url: str) -> None:
        self._deliver(email, "Your TruthLM sign-in link",
                      "Use this link to sign in to TruthLM. It expires in "
                      f"{self.settings.magic_link_minutes} minutes and can be used once.\n\n"
                      f"{verify_url}\n\nIf you did not request this link, you can ignore this email.")

    def send_access_approved(self, email: str, sign_in_url: str) -> None:
        self._deliver(email, "Your TruthLM invitation",
                      "You now have early access to TruthLM. Sign in with this email address to "
                      "ask research questions and upvote the ones you most want investigated.\n\n"
                      f"{sign_in_url}\n\nTruthLM will never ask for a password. If you did not "
                      "request access, you can ignore this email.")

    def _deliver(self, email: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.smtp_from_email
        message["To"] = email
        message.set_content(body)
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as client:
            if self.settings.smtp_starttls:
                client.starttls()
            if self.settings.smtp_username:
                client.login(self.settings.smtp_username, self.settings.smtp_password)
            client.send_message(message)


def default_mailer(settings: Settings) -> Mailer:
    return SMTPMailer(settings) if settings.email_delivery == "smtp" else ConsoleMailer()
