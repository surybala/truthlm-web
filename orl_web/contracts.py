"""Validation for vendored, language-neutral ORL boundary contracts."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError


class ContractError(ValueError):
    pass


@lru_cache(maxsize=None)
def _validator(name: str) -> Draft202012Validator:
    if name not in {"metrics-snapshot", "publication-bundle", "readiness-assessment", "research-request"}:
        raise ContractError(f"unknown contract {name!r}")
    path = Path(__file__).with_name("contracts") / "v1" / f"{name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_contract(name: str, payload: Mapping[str, Any]) -> None:
    try:
        _validator(name).validate(payload)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "$"
        raise ContractError(f"{name} violation at {location}: {exc.message}") from exc


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def content_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json({k: v for k, v in payload.items()
                                          if k != "content_sha256"})).hexdigest()


def verify_checksum(payload: Mapping[str, Any]) -> bool:
    return payload.get("content_sha256") == content_sha256(payload)
