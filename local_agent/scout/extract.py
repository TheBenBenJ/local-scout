"""Extraction déterministe de clés depuis une mission ou un corps de ticket. Pas de LLM."""

from __future__ import annotations

import re

from ..router import explicit_symbols

LYSI_KEY = re.compile(r"\bLYSI-\d+\b", re.IGNORECASE)
CONFLUENCE_URI = re.compile(r"confluence://(\d+)")
CONFLUENCE_PAGE = re.compile(
    r"(?:atlassian\.net)?/wiki/spaces/[^/\s]+/pages/(\d{6,})",
    re.IGNORECASE,
)
CONFLUENCE_PAGES = re.compile(r"/pages/(\d{6,})", re.IGNORECASE)
IMAGE_NAME = re.compile(r"\b(image-\d{8}-\d{6}\.(?:png|jpg|jpeg|webp))\b", re.IGNORECASE)
REPO_FILE = re.compile(r"\b((?:src|tests|assets|config)/[A-Za-z0-9_./-]+\.(?:php|ts|twig|yml|yaml))\b")
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
CAMEL_IDENT = re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]{3,}\b")

_NOISE_SYMBOLS = {
    "LYSI", "Jira", "Confluence", "SILAE", "HTTP", "JSON", "UUID",
    "Bonjour", "Merci", "Attendu", "Problème", "Correction",
    "Exemple", "Exemples", "Commentaire", "Conclusion",
}


def _uniq(items: list[str], *, limit: int) -> list[str]:
    seen: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def ticket_keys(text: str, *, primary: str | None = None, limit: int = 6) -> list[str]:
    found = [match.group(0).upper() for match in LYSI_KEY.finditer(text or "")]
    normalized = []
    for key in found:
        if key not in normalized:
            normalized.append(key)
    if primary:
        head = primary.strip().upper()
        if not head.startswith("LYSI-"):
            head = f"LYSI-{head}" if head.isdigit() else head
        rest = [item for item in normalized if item != head]
        return _uniq([head] + rest, limit=limit)
    return _uniq(normalized, limit=limit)


def confluence_ids(text: str, *, limit: int = 3) -> list[str]:
    found: list[str] = []
    for pattern in (CONFLUENCE_URI, CONFLUENCE_PAGE, CONFLUENCE_PAGES):
        for match in pattern.finditer(text or ""):
            found.append(match.group(1))
    return _uniq(found, limit=limit)


def image_names(text: str, *, limit: int = 8) -> list[str]:
    return _uniq([match.group(1) for match in IMAGE_NAME.finditer(text or "")], limit=limit)


def repo_files(text: str, *, limit: int = 8) -> list[str]:
    return _uniq([match.group(1) for match in REPO_FILE.finditer(text or "")], limit=limit)


def uuids(text: str, *, limit: int = 12) -> list[str]:
    return _uniq([match.group(0).lower() for match in UUID.finditer(text or "")], limit=limit)


def _useful(symbol: str) -> bool:
    if not symbol or symbol in _NOISE_SYMBOLS or symbol.upper().startswith("LYSI-"):
        return False
    if len(symbol) < 6:
        return False
    if symbol[0].islower() and any(ch.isupper() for ch in symbol[1:]):
        return True
    if symbol[0].isupper() and symbol.endswith(("Service", "Helper", "Factory", "Manager")):
        return True
    return False


def symbols(text: str, *, limit: int = 10) -> list[str]:
    found: list[str] = []
    for match in CAMEL_IDENT.findall(text or ""):
        if _useful(match) and match not in found:
            found.append(match)
    for item in explicit_symbols(text or ""):
        if _useful(item) and item not in found:
            found.append(item)
    methods = [item for item in found if item[0].islower()]
    classes = [item for item in found if item[0].isupper()]
    return _uniq(methods + classes, limit=limit)


def merge(head: list[str], tail: list[str], *, limit: int) -> list[str]:
    return _uniq(list(head) + list(tail), limit=limit)


def slug(mission: str, ticket: str | None) -> str:
    if ticket:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", ticket.strip())[:40].strip("-") or "mission"
    keys = ticket_keys(mission, limit=1)
    if keys:
        return keys[0]
    compact = re.sub(r"[^A-Za-z0-9]+", "-", (mission or "mission").strip())[:40].strip("-")
    return compact or "mission"
