"""Sign-in link, subscription notice, and research email delivery adapters."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from .config import Settings
from .delivery import ResearchEmail


class Mailer(Protocol):
    def send(self, email: str, verify_url: str) -> None: ...

    def send_access_approved(self, email: str, sign_in_url: str, unsubscribe_url: str) -> None: ...

    def send_research(self, email: str, message: ResearchEmail) -> None: ...


class ConsoleMailer:
    def send(self, email: str, verify_url: str) -> None:
        logging.getLogger("orl_web.auth").warning("Development sign-in link for %s: %s", email,
                                                  verify_url)

    def send_access_approved(self, email: str, sign_in_url: str, unsubscribe_url: str) -> None:
        logging.getLogger("orl_web.auth").warning("Development access approval for %s: %s", email,
                                                  sign_in_url)

    def send_research(self, email: str, message: ResearchEmail) -> None:
        logging.getLogger("orl_web.auth").warning("Development research email for %s: %s", email,
                                                  message.subject)


class SMTPMailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, email: str, verify_url: str) -> None:
        self._deliver(email, "Your TruthLM sign-in link",
                      "Use this link to sign in to TruthLM. It expires in "
                      f"{self.settings.magic_link_minutes} minutes and can be used once.\n\n"
                      f"{verify_url}\n\nIf you did not request this link, you can ignore this email.")

    def send_access_approved(self, email: str, sign_in_url: str, unsubscribe_url: str) -> None:
        self._deliver(email, "Your TruthLM subscription is active",
                      "Your TruthLM subscription is active. New investigations will arrive at this "
                      "address by email.\n\nTo choose the research domains and researchers you "
                      "follow, sign in with this email address. TruthLM never asks for a password.\n\n"
                      f"{sign_in_url}\n\nIf you did not request a subscription, or no longer want "
                      f"these emails, unsubscribe here: {unsubscribe_url}",
                      unsubscribe_url=unsubscribe_url)

    def send_research(self, email: str, message: ResearchEmail) -> None:
        self._deliver(email, message.subject, message.text, html=message.html,
                      unsubscribe_url=message.unsubscribe_url)

    def _deliver(self, email: str, subject: str, body: str, *, html: str = "",
                 unsubscribe_url: str = "") -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.smtp_from_email
        message["To"] = email
        if unsubscribe_url:
            message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        message.set_content(body)
        if html:
            message.add_alternative(html, subtype="html")
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as client:
            if self.settings.smtp_starttls:
                # smtplib's default context skips certificate verification.
                client.starttls(context=ssl.create_default_context())
            if self.settings.smtp_username:
                client.login(self.settings.smtp_username, self.settings.smtp_password)
            client.send_message(message)


def default_mailer(settings: Settings) -> Mailer:
    return SMTPMailer(settings) if settings.email_delivery == "smtp" else ConsoleMailer()
