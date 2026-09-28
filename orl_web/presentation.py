"""Deterministic reader-facing projections of immutable publication records."""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote


_NON_AUTHOR_LABELS = {"anonymous", "n/a", "none", "orl source", "unknown"}


def bibliographic_references(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return unique, reader-facing papers from the broader evidence registry.

    Publication bundles also retain search queries, datasets, computations, and internal notes for
    auditability. Those records are evidence, but they are not bibliographic references.
    """
    references: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for citation in citations:
        title = str(citation.get("title") or "").strip()
        year = citation.get("year")
        authors = [str(author).strip() for author in citation.get("authors") or []
                   if str(author).strip()
                   and str(author).strip().casefold() not in _NON_AUTHOR_LABELS]
        if not title or not isinstance(year, int) or isinstance(year, bool) or not authors:
            continue
        doi = str(citation.get("doi") or "").strip().casefold()
        title_key = " ".join(title.casefold().split())
        key = ("doi", doi) if doi else ("title", title_key, str(year))
        if key in seen:
            existing = next(reference for reference in references
                            if reference["_bibliographic_key"] == key)
            existing["citation_ids"].append(citation["citation_id"])
            continue
        seen.add(key)
        references.append({**citation, "title": title, "authors": authors,
                           "citation_ids": [citation["citation_id"]],
                           "_bibliographic_key": key})
    for reference in references:
        reference.pop("_bibliographic_key")
    return references


def _status(gates: list[dict], names: set[str]) -> str:
    selected = [gate for gate in gates if gate.get("name") in names]
    return "complete" if selected and all(gate.get("passed") for gate in selected) else "partial"


def _legacy_journey(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Give v1 bundles produced before research_journey a stable, meaningful projection."""
    experts = record.get("expert_contributions") or []
    evidence = record.get("evidence_map") or []
    computations = record.get("computations") or []
    disagreements = record.get("disagreements") or []
    methodology = record.get("methodology") or []
    refs = list(dict.fromkeys(
        ref for claim in evidence for key in ("supporting_citations", "contradicting_citations")
        for ref in claim.get(key, [])
    ))[:8]
    people = [item.get("expert") for item in experts if item.get("expert")]
    rows = [
        ("Framed the question", "complete",
         "The investigation defined its scope and assumptions before evaluating the evidence.",
         ["research_director"], []),
        ("Collected and screened evidence", "complete" if refs else "partial",
         f"The answer retained {len(refs)} cited evidence record(s) connected to public claims.",
         people, refs),
        ("Designed the investigation", "complete" if methodology else "partial",
         f"The public methodology records {len(methodology)} major research approach(es) and their completion status.",
         ["research_director"], refs),
        ("Ran independent expert inquiries", "complete" if experts else "partial",
         f"{len(experts)} expert perspective(s) examined the question from distinct disciplinary roles.",
         people, refs),
        ("Tested calculations and empirical claims", "complete" if computations else "not_applicable",
         f"The record contains {len(computations)} reproducible computation(s) or quantitative reconstruction(s).",
         people, refs),
        ("Compared competing interpretations", "complete" if disagreements else "not_applicable",
         (f"The consortium retained {len(disagreements)} material disagreement(s) and documented how each affected the answer."
          if disagreements else "No material unresolved disagreement was recorded for this investigation."),
         people, refs),
        ("Audited claims and limitations", "complete",
         f"The public evidence map records {len(evidence)} claim disposition(s), alongside limitations and open questions.",
         ["research_director"], refs),
        ("Built the reproducible research record", "complete",
         "The answer, evidence map, expert perspectives, computations, limitations, and signed audit record were assembled together.",
         ["research_director"], refs),
    ]
    return [{"sequence": index, "title": title, "status": status, "summary": summary,
             "participants": participants, "evidence_refs": evidence_refs}
            for index, (title, status, summary, participants, evidence_refs) in enumerate(rows, 1)]


def research_journey(record: Mapping[str, Any], gates: list[dict]) -> list[dict[str, Any]]:
    """Return the compact journey and add the Web-owned editorial/publication stage."""
    source = record.get("research_journey")
    journey = ([dict(item) for item in source]
               if isinstance(source, list) and 6 <= len(source) <= 10 else _legacy_journey(record))
    if len(journey) < 10 and not any(item.get("title") == "Editorial review and publication"
                                     for item in journey):
        editorial_status = _status(gates, {"editorial_review"})
        journey.append({
            "sequence": len(journey) + 1,
            "title": "Editorial review and publication",
            "status": editorial_status,
            "summary": ("A TruthLM editor approved the complete research bundle and released this revision."
                        if editorial_status == "complete"
                        else "The complete research bundle is awaiting independent editorial approval."),
            "participants": ["truthlm_editor"],
            "evidence_refs": [],
        })
    return journey


def share_links(url: str, title: str, summary: str) -> list[dict[str, str]]:
    """Plain share-intent links; no third-party script is ever loaded to share an article."""
    def enc(value: str) -> str:
        return quote(value, safe="")
    post = f"{title} — TruthLM"
    email_body = f"{summary}\n\n{url}"
    return [
        {"network": "linkedin", "label": "LinkedIn",
         "href": f"https://www.linkedin.com/sharing/share-offsite/?url={enc(url)}"},
        {"network": "x", "label": "X",
         "href": f"https://x.com/intent/tweet?text={enc(post)}&url={enc(url)}"},
        {"network": "bluesky", "label": "Bluesky",
         "href": f"https://bsky.app/intent/compose?text={enc(post + ' ' + url)}"},
        {"network": "facebook", "label": "Facebook",
         "href": f"https://www.facebook.com/sharer/sharer.php?u={enc(url)}"},
        {"network": "reddit", "label": "Reddit",
         "href": f"https://www.reddit.com/submit?url={enc(url)}&title={enc(title)}"},
        {"network": "email", "label": "Email",
         "href": f"mailto:?subject={enc(title)}&body={enc(email_body)}"},
    ]
