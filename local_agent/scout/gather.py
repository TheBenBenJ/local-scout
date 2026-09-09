"""Chargement déterministe : Jira, Confluence, OCR, rg. Zéro LLM."""

from __future__ import annotations

import time
from pathlib import Path

from .. import files, ocr
from ..config import Config
from ..files import DECLARATION
from ..providers import confluence as confluence_provider
from ..providers import jira as jira_provider
from . import extract
from .dossier import Dossier

_PHP_GLOBS = ["*.php", "!**/vendor/**", "!**/tests/**"]
_HITS_PER_SYMBOL = 3


def _uniq_files(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        text = str(item or "").strip().lstrip("/")
        if text and text not in seen:
            seen.append(text)
    return seen[:8]


def _mark(dossier: Dossier, name: str, started: float) -> None:
    dossier.ledger.phases_s[name] = round(time.monotonic() - started, 2)


def gather(
    config: Config,
    mission: str,
    *,
    ticket: str | None = None,
    sources: list[str] | None = None,
    out_dir: Path,
) -> Dossier:
    blob = "\n".join([mission or "", ticket or "", "\n".join(sources or [])])
    keys = extract.ticket_keys(blob, primary=ticket)
    page_ids = extract.confluence_ids(blob)
    named_files = extract.repo_files(blob)
    head_symbols = extract.symbols(blob)
    named_ids = extract.uuids(blob)
    extra_uris = [item for item in (sources or []) if str(item).strip()]
    extra_images: list[Path] = []

    for uri in extra_uris:
        lowered = uri.lower()
        if lowered.startswith("jira://"):
            keys = extract.ticket_keys(uri.split("://", 1)[-1] + "\n" + " ".join(keys), primary=ticket)
        elif lowered.startswith("confluence://"):
            page_ids = extract.confluence_ids(uri + "\n" + " ".join(page_ids))
        elif lowered.startswith("repo://"):
            named_files = extract.repo_files(uri.split("://", 1)[-1] + "\n" + " ".join(named_files))
            if "/" in uri.split("://", 1)[-1]:
                named_files = _uniq_files(named_files + [uri.split("://", 1)[-1]])
        elif lowered.startswith("image://") or Path(uri).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            raw = uri.split("://", 1)[-1] if lowered.startswith("image://") else uri
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = config.repo_root / path
            if path.is_file():
                extra_images.append(path)

    dossier = Dossier(mission=mission.strip(), ids=named_ids)
    pieces = out_dir / "pieces"
    pending_images: list[Path] = list(extra_images[:8])
    body_symbols: list[str] = []

    started = time.monotonic()
    fetched: set[str] = set()
    for key in keys:
        if key in fetched:
            continue
        fetched.add(key)
        packed = jira_provider.fetch(key, config.repo_root)
        if packed.get("error"):
            dossier.errors.append(f"{key}: {packed.get('error')}")
            continue
        dossier.tickets.append(packed)
        dossier.ledger.add_text("jira", str(packed.get("acceptance_criteria_verbatim") or ""))
        for comment in packed.get("comments") or []:
            dossier.ledger.add_text("jira", str(comment.get("body") or ""))
        text = _ticket_text(packed)
        page_ids = extract.merge(page_ids, extract.confluence_ids(text), limit=3)
        body_symbols = extract.merge(body_symbols, extract.symbols(text), limit=16)
        named_files = extract.merge(named_files, extract.repo_files(text), limit=8)
        for extra in extract.ticket_keys(text):
            if extra not in keys and len(keys) < 6:
                keys.append(extra)
        try:
            pending_images.extend(jira_provider.save_images(packed, pieces, config.repo_root))
        except Exception as error:  # noqa: BLE001
            dossier.errors.append(f"{key} pièces: {error}")
    _mark(dossier, "jira", started)

    started = time.monotonic()
    seen_paths: set[str] = set()
    for path in pending_images:
        resolved = str(path.resolve()) if path.exists() else str(path)
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        _ocr_one(config, dossier, path)
    _mark(dossier, "ocr", started)

    started = time.monotonic()
    for page_id in page_ids[:3]:
        packed = confluence_provider.fetch(page_id, config.repo_root)
        if packed.get("error"):
            dossier.errors.append(f"confluence {page_id}: {packed.get('error')}")
            continue
        dossier.pages.append(packed)
        dossier.ledger.add_text("confluence", str(packed.get("body") or packed.get("text") or ""))
    _mark(dossier, "confluence", started)

    named_symbols = extract.merge(head_symbols, body_symbols, limit=10)
    started = time.monotonic()
    seen_files = {item.get("file") for item in dossier.code}
    for symbol in named_symbols[:8]:
        _grep_symbol(config, dossier, symbol, seen_files)
    already = {item.get("file") for item in dossier.code}
    for relative in named_files[:8]:
        if relative in already:
            continue
        _grep_file(config, dossier, relative)
    _mark(dossier, "code", started)

    dossier.raw_chars = dossier.ledger.text_chars()
    if not keys:
        dossier.holes.append("Aucune clé LYSI-XXXX dans la mission.")
    if keys and not dossier.tickets:
        dossier.holes.append("Tickets demandés mais non chargés (auth Jira ou réseau).")
    if not dossier.images:
        dossier.holes.append("Aucune capture OCR (pas de pièce image, ou téléchargement refusé).")
    if named_symbols and not dossier.code:
        dossier.holes.append("Symboles nommés mais aucun hit rg (chemin ou nom).")
    if not named_symbols and not named_files:
        dossier.holes.append(
            "Aucun symbole ni fichier repo dans les sources. Les nommer dans la mission ou passer --source repo://…"
        )
    return dossier


def _ticket_text(packed: dict) -> str:
    comments = "\n".join(str(item.get("body") or "") for item in (packed.get("comments") or []))
    return "\n".join(
        [
            str(packed.get("goal") or ""),
            str(packed.get("acceptance_criteria_verbatim") or ""),
            comments,
            " ".join(str(item) for item in (packed.get("attachments") or [])),
        ]
    )


def _ocr_one(config: Config, dossier: Dossier, path: Path) -> None:
    from .. import evidence

    try:
        ocr.read_images(config, None, [str(path)])
        packet = evidence.load(ocr.image_id_for(path))
        transcript = str(packet.get("transcript") or "")
    except Exception as error:  # noqa: BLE001
        dossier.errors.append(f"OCR {path.name}: {error}")
        return
    dossier.images.append(
        {
            "name": path.name,
            "path": str(path),
            "transcript": transcript[:4000],
        }
    )
    if path.is_file():
        dossier.ledger.add_image_file(path)
    dossier.ledger.add_text("ocr", transcript)


def _rank_matches(matches: list[dict]) -> list[dict]:
    decls: list[dict] = []
    rest: list[dict] = []
    for match in matches:
        if DECLARATION.match(str(match.get("text") or "")):
            decls.append(match)
        else:
            rest.append(match)
    return decls + rest


def _grep_symbol(config: Config, dossier: Dossier, symbol: str, seen_files: set) -> None:
    try:
        matches, _total = files.grep(
            config,
            config.repo_root / "src",
            [symbol],
            globs=_PHP_GLOBS,
            max_matches=12,
            ignore_case=False,
            max_count_per_file=2,
        )
    except Exception as error:  # noqa: BLE001
        dossier.errors.append(f"rg {symbol}: {error}")
        return
    kept = 0
    for match in _rank_matches(matches):
        if kept >= _HITS_PER_SYMBOL:
            break
        relative = str(match.get("file") or "")
        line = match.get("line")
        location = f"{relative}:{line}" if line else relative
        snippet = str(match.get("text") or "")[:220]
        dossier.code.append(
            {
                "file": relative,
                "location": location,
                "symbol": symbol,
                "text": snippet,
            }
        )
        dossier.ledger.add_text("code", snippet)
        if relative:
            seen_files.add(relative)
        kept += 1


def _grep_file(config: Config, dossier: Dossier, relative: str) -> None:
    path = config.repo_root / relative
    if not path.is_file():
        dossier.holes.append(f"fichier nommé absent : {relative}")
        return
    try:
        text, _truncated = files.read_text(path, min(8000, getattr(config, "max_file_size", 12000)))
    except Exception as error:  # noqa: BLE001
        dossier.errors.append(f"{relative}: {error}")
        return
    excerpt = "\n".join(text.splitlines()[:80])[:1500]
    dossier.code.append({"file": relative, "location": relative, "text": excerpt})
    dossier.ledger.add_text("code", excerpt)
