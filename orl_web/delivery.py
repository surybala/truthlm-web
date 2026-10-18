"""Research email composition and signed unsubscribe links."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class ResearchEmail:
    subject: str
    text: str
    html: str
    unsubscribe_url: str


@dataclass(frozen=True)
class EmailItem:
    title: str
    summary: str
    url: str
    domains: tuple[str, ...]


DISCLOSURE = ("Each investigation is researched by AI agents and reviewed by a person before "
              "publication. It is scientific analysis for learning and research, not medical, legal, "
              "or investment advice.")


def unsubscribe_signature(user_id: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"unsubscribe:{user_id}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def unsubscribe_url(base_url: str, user_id: str, secret: str) -> str:
    return f"{base_url}/unsubscribe/{user_id}/{unsubscribe_signature(user_id, secret)}"


def valid_unsubscribe(user_id: str, signature: str, secret: str) -> bool:
    return hmac.compare_digest(signature, unsubscribe_signature(user_id, secret))


def compose_research_email(items: list[EmailItem], *, base_url: str,
                           unsubscribe: str) -> ResearchEmail:
    subject = (f"New on TruthLM: {items[0].title}" if len(items) == 1
               else f"{len(items)} new TruthLM investigations")
    preferences = f"{base_url}/subscriptions"
    text_items = []
    html_items = []
    for item in items:
        domains = " · ".join(item.domains)
        text_items.append("\n".join(part for part in (
            item.title, domains, item.summary, f"Read it: {item.url}") if part))
        html_items.append(
            f'<li><p><a href="{escape(item.url)}"><strong>{escape(item.title)}</strong></a></p>'
            + (f"<p><small>{escape(domains)}</small></p>" if domains else "")
            + f"<p>{escape(item.summary)}</p></li>")
    text = "\n\n".join([
        "New research from TruthLM", *text_items, DISCLOSURE,
        f"You receive this because you subscribed to TruthLM research.\n"
        f"Choose the domains and researchers you follow: {preferences}\n"
        f"Unsubscribe: {unsubscribe}",
    ]) + "\n"
    html = (
        "<!doctype html><html><body>"
        "<h1>New research from TruthLM</h1>"
        f"<ul>{''.join(html_items)}</ul>"
        f"<p>{escape(DISCLOSURE)}</p>"
        "<p>You receive this because you subscribed to TruthLM research. "
        f'<a href="{escape(preferences)}">Choose the domains and researchers you follow</a> · '
        f'<a href="{escape(unsubscribe)}">Unsubscribe</a></p>'
        "</body></html>"
    )
    return ResearchEmail(subject=subject, text=text, html=html, unsubscribe_url=unsubscribe)
