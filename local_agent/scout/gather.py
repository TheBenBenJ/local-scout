"""Chargement déterministe : sources fermées, Annot PDF, Jira opt-in, OCR borné."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from .. import files, ocr
from ..config import Config
from ..providers import confluence as confluence_provider
from ..providers import gitlab as gitlab_provider
from ..providers import jira as jira_provider
from . import code as code_x
from . import extract
from . import gitarch
from . import logs as log_x
from . import pdf as pdf_x
from .dossier import Dossier

_IMAGE_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_LOG_BYTES = 5_000_000
OCR_MAX_IMAGES = 20


def gather(
    config: Config,
    mission: str,
    *,
    ticket: str | None = None,
    sources: list[str] | None = None,
    out_dir: Path,
) -> Dossier:
    extra_uris = [item for item in (sources or []) if str(item).strip()]
    closed = bool(extra_uris)
    blob = "\n".join([mission or "", ticket or "", "\n".join(extra_uris)])
    listed = extract.source_paths(extra_uris, limit=16)
    if not closed:
        listed = extract.prefer_full_paths(
            extract.merge(listed, extract.repo_files(blob, limit=12), limit=12)
        )
    listed = extract.prefer_full_paths(listed)

    keys: list[str] = []
    source_keys: list[str] = []
    page_ids: list[str] = []
    extra_images: list[Path] = []
    log_sources: list[str] = []
    ci_sources: list[str] = []
    git_patterns: list[str] = []
    cql_queries: list[str] = []
    if ticket:
        keys = extract.ticket_keys(ticket, primary=ticket)
    for uri in extra_uris:
        lowered = uri.lower()
        if lowered.startswith("jira://"):
            source_keys = extract.merge(
                source_keys,
                extract.ticket_keys(uri.split("://", 1)[-1]),
                limit=6,
            )
        elif lowered.startswith("confluence://"):
            found = extract.confluence_ids(uri)
            # confluence://ESPACE/Titre : le provider sait chercher par titre, ne pas l'ignorer.
            ident = uri.split("://", 1)[-1].strip()
            page_ids = extract.merge(page_ids, found or ([ident] if ident else []), limit=3)
        elif lowered.startswith("image://") or Path(uri).suffix.lower() in _IMAGE_SUFFIX:
            extra_images.append(_resolve(config, uri.split("://", 1)[-1] if lowered.startswith("image://") else uri))
        elif lowered.startswith("log://"):
            log_sources.append(uri.split("://", 1)[-1])
        elif lowered.startswith("ci://"):
            ci_sources.append(uri.split("://", 1)[-1])
        elif lowered.startswith("git://"):
            git_patterns.append(uri.split("://", 1)[-1])
        elif lowered.startswith("cql://"):
            cql_queries.append(uri.split("://", 1)[-1])

    extraction = extract.is_extraction(mission)
    primary_key = keys[0] if keys else ""
    if not primary_key and not closed:
        mission_keys = extract.ticket_keys(mission)
        if mission_keys:
            primary_key = mission_keys[0]
    if not primary_key and source_keys:
        primary_key = source_keys[0]
    keys = extract.merge([primary_key] if primary_key else [], source_keys, limit=6)
    if not closed:
        keys = extract.merge(keys, extract.ticket_keys(blob), limit=6)
        page_ids = extract.merge(page_ids, extract.confluence_ids(blob), limit=3)

    dossier = Dossier(mission=mission.strip(), ids=extract.uuids(blob), primary_key=primary_key)
    pieces = out_dir / "pieces"
    review = extract.is_review(mission) and any(extract.is_code_path(item) for item in listed)
    named_images = {name.lower() for name in extract.image_names(mission)}
    ocr_paths = [path for path in extra_images if path.is_file()]
    for relative in listed:
        path = _resolve(config, relative)
        if path.is_file() and extract.is_image_path(relative):
            if path not in ocr_paths:
                ocr_paths.append(path)
        if path.is_file() and path.name.lower() in named_images and path not in ocr_paths:
            ocr_paths.append(path)

    started = time.monotonic()
    body_symbols: list[str] = []
    ticket_blob = ""
    fetched: set[str] = set()
    linked_keys = {item for item in source_keys if item != primary_key}
    for key in keys:
        if key in fetched:
            continue
        fetched.add(key)
        linked = key in linked_keys
        packed = jira_provider.fetch(key, config.repo_root, attachments=not linked)
        if packed.get("error"):
            err = str(packed.get("error") or "")
            if "HTTP 404" in err:
                dossier.holes.append(f"{key}: ticket 404")
                dossier.missed.append(f"{key}: ticket 404")
            else:
                dossier.errors.append(f"{key}: {err}")
            continue
        packed["role"] = "linked" if linked else "primary"
        packed["asked_empty_fields"] = [
            name for name in (packed.get("empty_fields") or []) if name.lower() in mission.lower()
        ]
        asked = [
            field for field in (packed.get("option_fields") or []) if field["name"].lower() in mission.lower()
        ]
        packed["custom_fields"] = asked + list(packed.get("custom_fields") or [])
        if not linked:
            packed["full_path"] = _write_ticket(config, packed, out_dir / "tickets")
            packed["comment_limit"] = 12 if extract.wants_comments(mission) else 6
        packed["show_comments"] = not linked and (extraction or extract.wants_comments(mission))
        dossier.tickets.append(packed)
        dossier.read_sources.append(f"jira://{key}")
        dossier.ledger.add_text("jira", str(packed.get("acceptance_criteria_verbatim") or ""))
        if not linked:
            for comment in packed.get("comments") or []:
                dossier.ledger.add_text("jira", str(comment.get("body") or ""))
        text = _ticket_text(packed) if not linked else str(packed.get("acceptance_criteria_verbatim") or "")
        if not linked:
            ticket_blob += "\n" + text
        if not closed and not linked:
            page_ids = extract.merge(page_ids, extract.confluence_ids(text), limit=3)
            listed = extract.prefer_full_paths(
                extract.merge(listed, extract.repo_files(text, limit=8), limit=12)
            )
        if not linked:
            body_symbols = extract.merge(body_symbols, extract.symbols(text), limit=16)
            if not closed:
                for extra in extract.ticket_keys(text):
                    if extra not in keys and len(keys) < 6:
                        keys.append(extra)
        if (
            not linked
            and (extraction or extract.wants_ocr(mission, text))
            and packed.get("attachment_files")
        ):
            saved = jira_provider.save_images(packed, pieces, config.repo_root, limit=OCR_MAX_IMAGES)
            if saved:
                packed["pieces_dir"] = _relative(config, pieces)
            for path in saved:
                if path not in ocr_paths:
                    ocr_paths.append(path)
    _mark(dossier, "jira", started)
    _run_jira_search(config, dossier, mission, keys)

    started = time.monotonic()
    seen_ocr: set[str] = set()
    for path in ocr_paths[:OCR_MAX_IMAGES]:
        resolved = str(path.resolve()) if path.exists() else str(path)
        if resolved in seen_ocr:
            continue
        seen_ocr.add(resolved)
        _ocr_one(config, dossier, path, out_dir / "ocr")
        dossier.read_sources.append(_relative(config, path))
    skipped = ocr_paths[OCR_MAX_IMAGES:]
    if skipped:
        names = ", ".join(path.name for path in skipped[:10])
        dossier.missed.append(f"{len(skipped)} capture(s) non lue(s) par scout (plafond {OCR_MAX_IMAGES}) : {names}")
        for path in skipped:
            dossier.allow_reread(_relative(config, path), "capture au-delà du plafond OCR")
    _mark(dossier, "ocr", started)

    started = time.monotonic()
    for raw in log_sources[:4]:
        _load_log(config, dossier, raw)
    for raw in ci_sources[:4]:
        _load_ci(config, dossier, raw)
    _mark(dossier, "logs", started)

    started = time.monotonic()
    for pattern in git_patterns[:4]:
        packed = gitarch.find_branches(pattern, config.repo_root)
        dossier.branches.append(packed)
        dossier.read_sources.append(f"git://{pattern}")
        if packed.get("error"):
            dossier.errors.append(f"git://{pattern}: {packed['error']}")
    _mark(dossier, "git", started)

    diagnosis = extract.is_ticket_diagnosis(mission, keys, listed)
    started = time.monotonic()
    for page_id in page_ids[:3]:
        packed = confluence_provider.fetch(page_id, config.repo_root)
        if packed.get("error"):
            dossier.errors.append(f"confluence {page_id}: {packed.get('error')}")
            continue
        packed["full_path"] = _write_page(config, packed, out_dir / "pages")
        dossier.pages.append(packed)
        dossier.read_sources.append(f"confluence://{page_id}")
        dossier.ledger.add_text("confluence", str(packed.get("body") or packed.get("text") or ""))
    need_page = not extraction or extract.wants_confluence(mission)
    for query in cql_queries[:3]:
        found = confluence_provider.search(query, config.repo_root, limit=5)
        results = list(found.get("results") or [])
        for item in results:
            item["full_path"] = _write_page(config, item, out_dir / "pages")
        dossier.confluence_searches.append(
            {"query": query, "results": results, "error": found.get("error") if not results else None}
        )
        dossier.read_sources.append(f"cql://{query}")
        for item in results:
            dossier.ledger.add_text("confluence", str(item.get("body") or ""))
    if diagnosis and need_page and not dossier.pages:
        goal = str(dossier.tickets[0].get("goal") or "") if dossier.tickets else ""
        query = extract.confluence_query(mission, ticket_blob, goal)
        found = (
            confluence_provider.search(query, config.repo_root)
            if query
            else {"results": [], "error": "aucun terme de domaine dans le ticket ni la mission"}
        )
        results = list(found.get("results") or [])
        if found.get("error") and not results:
            dossier.confluence_note = f"non cherchée : {found.get('error')}"
        for item in results[:2]:
            dossier.pages.append(item)
            page_id = str(item.get("id") or "")
            if page_id:
                dossier.read_sources.append(f"confluence://{page_id}")
            dossier.ledger.add_text("confluence", str(item.get("quote") or item.get("body") or ""))
        if not dossier.pages and not dossier.confluence_note:
            dossier.confluence_note = f"cherchée, 0 page pour {query!r}"
    _mark(dossier, "confluence", started)

    named_symbols = extract.merge(extract.symbols(blob, limit=16), body_symbols, limit=12)
    started = time.monotonic()
    seen_files: set[str] = set()
    code_listed: list[str] = []
    for relative in listed:
        path = _resolve(config, relative)
        if path.is_dir():
            _load_directory(config, dossier, relative, path, mission)
            continue
        if extract.is_pdf_path(relative) or path.suffix.lower() == ".pdf":
            _load_pdf(config, dossier, relative, path, mission)
            continue
        if extract.is_image_path(relative):
            if _relative(config, path) not in dossier.read_sources:
                if path.is_file() and path not in ocr_paths:
                    dossier.indexes.append(
                        {
                            "path": relative,
                            "bytes": path.stat().st_size if path.is_file() else 0,
                            "note": "image listée, OCR non demandé par la mission",
                        }
                    )
                    dossier.read_sources.append(relative)
            continue
        if path.is_file() or extract.is_code_path(relative):
            code_listed.append(relative)
            code_x.load_named_file(config, dossier, relative, named_symbols, review=review, listed=True)
            for item in dossier.code:
                if item.get("file"):
                    seen_files.add(str(item["file"]))
                    if str(item["file"]) not in dossier.read_sources:
                        dossier.read_sources.append(str(item["file"]))
            if relative not in dossier.read_sources and (config.repo_root / relative).is_file():
                dossier.read_sources.append(relative)
    if review and code_listed:
        for symbol in named_symbols[:10]:
            _grep_symbol(config, dossier, symbol, seen_files)
        code_x.review_pass(config, dossier, code_listed, named_symbols, seen_files)
        extra = extract.symbols("\n".join(str(item.get("text") or "") for item in dossier.code), limit=10)
        for symbol in extra:
            if symbol in named_symbols:
                continue
            _grep_symbol(config, dossier, symbol, seen_files)
            named_symbols.append(symbol)
        for item in dossier.code:
            if item.get("file") and str(item["file"]) not in dossier.read_sources:
                dossier.read_sources.append(str(item["file"]))
    elif diagnosis and (not extraction or extract.wants_screen(mission) or extract.symbols(blob)):
        slugs = extract.url_slugs(f"{ticket_blob}\n{mission}")
        camel = ["".join(part.capitalize() for part in re.split(r"[-_]", slug)) for slug in slugs]
        needles = extract.merge(extract.merge(named_symbols, slugs, limit=12), camel, limit=12)
        code_x.screen_pass(config, dossier, needles, seen_files)
        dossier.code = dossier.code[:3]
        for item in dossier.code:
            if item.get("file") and str(item["file"]) not in dossier.read_sources:
                dossier.read_sources.append(str(item["file"]))
    elif not closed:
        for symbol in named_symbols[:10]:
            _grep_symbol(config, dossier, symbol, seen_files)
    _mark(dossier, "code", started)

    _type_url_uuids(config, dossier, f"{ticket_blob}\n{mission}", report_holes=not extraction)
    dossier.raw_chars = dossier.ledger.text_chars()
    if extract.is_grep_mission(mission):
        for symbol in named_symbols:
            if dossier.rg_counts.get(symbol) == 0:
                dossier.holes.append(f"rg 0 match : {symbol}")
                dossier.absence_guard = True
    _finalize_coverage(config, dossier, mission, listed, keys, diagnosis=diagnosis, extraction=extraction)
    return dossier


def _resolve(config: Config, raw: str) -> Path:
    text = (raw or "").strip()
    if text.lower().startswith("repo://"):
        text = text.split("://", 1)[-1]
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = config.repo_root / path
    return path


def _relative(config: Config, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(config.repo_root.resolve()))
    except ValueError:
        return str(path)


def _load_directory(config: Config, dossier: Dossier, relative: str, path: Path, mission: str) -> None:
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name.lower())
    except OSError as error:
        dossier.holes.append(f"{relative}: source demandée illisible")
        dossier.missed.append(f"{relative}: dossier illisible ({error})")
        dossier.allow_reread(relative, f"dossier illisible : {error}")
        return
    rows = []
    pdfs: list[str] = []
    images: list[str] = []
    for child in children[:40]:
        try:
            stat = child.stat()
        except OSError:
            continue
        child_rel = f"{relative.rstrip('/')}/{child.name}"
        kind = "dir" if child.is_dir() else child.suffix.lower() or "file"
        rows.append(
            f"- `{child_rel}` · {kind} · {stat.st_size} octets · "
            f"{datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')}"
        )
        if child.suffix.lower() == ".pdf":
            pdfs.append(child_rel)
        if child.suffix.lower() in _IMAGE_SUFFIX:
            images.append(child_rel)
    dossier.indexes.append({"path": relative, "entries": rows, "pdfs": pdfs, "images": images})
    dossier.read_sources.append(relative)
    dossier.ledger.add_text("code", "\n".join(rows))
    if extract.wants_annots(mission) or any(extract.is_pdf_path(item) for item in pdfs):
        if pdfs:
            dossier.missed.append(
                f"{relative}: index seulement ; annots PDF non extraits. Passer le fichier, pas le dossier."
            )
            for pdf_rel in pdfs:
                dossier.allow_reread(pdf_rel, "source dossier : ouvrir le PDF pour les Annot")
        else:
            dossier.missed.append(f"{relative}: aucun PDF dans l'index, extracteur Annot non exercé sur un fichier.")
    if extract.wants_ocr(mission) and images:
        named = {name.lower() for name in extract.image_names(mission)}
        hits = [item for item in images if Path(item).name.lower() in named]
        if not hits:
            dossier.missed.append(
                f"{relative}: {len(images)} images indexées, OCR non lancé (pas de chemin image dans sources)."
            )


def _load_pdf(config: Config, dossier: Dossier, relative: str, path: Path, mission: str) -> None:
    if not path.is_file():
        dossier.missed.append(f"{relative}: PDF demandé introuvable")
        dossier.allow_reread(relative, "PDF absent à ce chemin")
        dossier.absence_guard = True
        dossier.locations.append(f"non trouvé à {relative}")
        return
    packed = pdf_x.extract_annots(path, want_page_text=extract.wants_pdf_text(mission))
    dossier.read_sources.append(relative)
    if packed.get("error"):
        dossier.missed.append(f"{relative}: {packed['error']}")
        dossier.allow_reread(relative, str(packed["error"]))
        dossier.holes.append(f"{relative}: source demandée illisible")
        return
    annots = list(packed.get("annots") or [])
    if not annots:
        dossier.missed.append(
            f"{relative}: extracteur Annot exercé, 0 Highlight/Text/FreeText/StrikeOut/Caret/Stamp."
        )
        if extract.wants_handwriting(mission):
            dossier.missed.append(
                f"{relative}: raster+OCR non lancé (PDF n'est pas une capture ; pas de convertisseur PDF→PNG branché)."
            )
            dossier.allow_reread(relative, "annots vides ; raster manuscrit non exercé")
        elif not packed.get("pdftotext") and extract.wants_pdf_text(mission):
            dossier.missed.append(f"{relative}: pdftotext absent, texte de page non lu.")
            dossier.allow_reread(relative, "pdftotext absent")
        return
    for annot in annots:
        excerpt_id = code_x.next_excerpt_id(dossier)
        annot["id"] = excerpt_id
        annot["file"] = relative
        dossier.annots.append(annot)
        dossier.ledger.add_text("code", str(annot.get("contents") or annot.get("passage") or ""))
    if extract.wants_pdf_text(mission) and not packed.get("pdftotext"):
        dossier.allow_reread(relative, "texte de page : pdftotext absent, annots OK")


def _write_page(config: Config, packed: dict, directory: Path) -> str:
    """Page intégrale en texte sur disque : citer mot pour mot sans rappeler Confluence."""
    body = str(packed.get("body") or packed.get("text") or "")
    if not body.strip():
        return ""
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", str(packed.get("id") or packed.get("page") or "page")).strip("-")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name or 'page'}.md"
        target.write_text(f"# {packed.get('title') or ''}\n\n{body}\n", encoding="utf-8")
    except OSError:
        return ""
    return _relative(config, target)


def _write_ticket(config: Config, packed: dict, directory: Path) -> str:
    """Ticket intégral en texte sur disque : le drill-down lit ce fichier, pas un second appel Jira."""
    lines = [
        f"# {packed.get('key')} — {packed.get('goal')}",
        f"Type : {packed.get('issuetype')} · Statut : {packed.get('status')} · Priorité : {packed.get('priority') or '?'}",
        "",
        "## Description",
        str(packed.get("acceptance_criteria_verbatim") or ""),
    ]
    for field in list(packed.get("option_fields") or []) + list(packed.get("custom_fields") or []):
        lines.extend(["", f"## {field.get('name')}", str(field.get("text") or "")])
    comments = packed.get("comments") or []
    lines.extend(["", f"## Commentaires ({len(comments)})"])
    for comment in comments:
        lines.extend(["", f"### {comment.get('created')} {comment.get('author')}", str(comment.get("body") or "")])
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{packed.get('key')}.md"
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if packed.get("raw") is not None:
            # Réponse API telle quelle : les skills qui veulent un contexte.json n'ont pas à rappeler Jira.
            (directory / f"{packed.get('key')}.json").write_text(
                json.dumps(packed["raw"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            packed["raw_path"] = _relative(config, directory / f"{packed.get('key')}.json")
    except OSError:
        return ""
    return _relative(config, target)


def _load_log(config: Config, dossier: Dossier, raw: str) -> None:
    path = _resolve(config, raw)
    relative = _relative(config, path)
    if not path.is_file():
        dossier.missed.append(f"log://{raw}: fichier introuvable")
        dossier.allow_reread(f"log://{raw}", "log absent à ce chemin")
        return
    try:
        data = path.read_bytes()
    except OSError as error:
        dossier.errors.append(f"log://{raw}: {error}")
        return
    read_truncated = len(data) > _MAX_LOG_BYTES
    text = data[:_MAX_LOG_BYTES].decode("utf-8", errors="replace")
    packed = log_x.extract_failures(text)
    packed["label"] = relative
    dossier.logs.append(packed)
    dossier.read_sources.append(f"log://{relative}")
    dossier.ledger.add_text("log", packed.get("kept") or "")
    if packed.get("truncated") or read_truncated:
        dossier.truncated_sources.append(
            {
                "path": f"log://{relative}",
                "kept_lines": packed.get("kept_lines"),
                "total_lines": packed.get("total_lines"),
                "kept_bytes": packed.get("kept_bytes"),
                "total_bytes": packed.get("total_bytes"),
                "ids": [],
            }
        )


def _load_ci(config: Config, dossier: Dossier, raw: str) -> None:
    parts = [part for part in raw.split("/") if part]
    if not parts or parts[0].lower() != "gitlab":
        dossier.errors.append(f"ci://{raw}: provider non supporté (gitlab seulement)")
        return
    rest = parts[1:]
    if not rest:
        dossier.errors.append(f"ci://{raw}: job id manquant")
        return
    job_id = rest[-1]
    project = "/".join(rest[:-1])
    packed = gitlab_provider.fetch_trace(job_id, project=project, repo_root=config.repo_root)
    if packed.get("error"):
        dossier.errors.append(f"ci://{raw}: {packed['error']}")
        return
    trace = packed.get("trace") or ""
    filtered = log_x.extract_failures(trace)
    filtered["label"] = f"ci://gitlab/{packed.get('project') or project}/{job_id}"
    dossier.logs.append(filtered)
    dossier.read_sources.append(f"ci://{raw}")
    dossier.ledger.add_text("log", filtered.get("kept") or "")
    if filtered.get("truncated"):
        dossier.truncated_sources.append(
            {
                "path": f"ci://{raw}",
                "kept_lines": filtered.get("kept_lines"),
                "total_lines": filtered.get("total_lines"),
                "kept_bytes": filtered.get("kept_bytes"),
                "total_bytes": filtered.get("total_bytes"),
                "ids": [],
            }
        )


def _finalize_coverage(
    config: Config,
    dossier: Dossier,
    mission: str,
    listed: list[str],
    keys: list[str],
    *,
    diagnosis: bool,
    extraction: bool = False,
) -> None:
    for relative in listed:
        path = _resolve(config, relative)
        if path.is_file() and (extract.is_pdf_path(relative) or path.suffix.lower() == ".pdf"):
            if not any(item.get("file") == relative for item in dossier.annots):
                if not any(relative in item for item in dossier.missed):
                    dossier.missed.append(f"{relative}: PDF listé, annots non extraits")
                    dossier.allow_reread(relative, "PDF listé sans extraits Annot")
            continue
        if path.is_dir():
            continue
        if path.is_file() and extract.is_code_path(relative):
            if relative not in dossier.read_sources and not any(
                item.get("file") == relative for item in dossier.code
            ):
                dossier.missed.append(f"{relative}: demandé, non extrait")
                dossier.allow_reread(relative, "source listée non extraite")
            continue
        if not path.exists() and relative not in dossier.read_sources:
            if not any(relative in item for item in dossier.missed + dossier.locations):
                dossier.missed.append(f"{relative}: demandé, non extrait")
                dossier.allow_reread(relative, "source listée non extraite")
    if extract.wants_annots(mission) and not dossier.annots:
        if not any("annot" in item.lower() or "PDF" in item for item in dossier.missed):
            dossier.missed.append("mission annots PDF : extracteur Annot non exercé (aucun PDF dans sources).")
    if keys and not dossier.tickets:
        if not any("ticket 404" in item for item in dossier.missed):
            dossier.errors.append("Tickets demandés mais non chargés (auth Jira ou réseau).")

    if extract.wants_jira_search(mission):
        if dossier.jira_search is None:
            dossier.jira_search = {
                "jql": extract.build_jql(mission, exclude=keys),
                "error": "recherche Jira non exécutée : non lancée",
                "results": [],
                "total": 0,
            }
        err = dossier.jira_search.get("error")
        if err:
            text = str(err)
            _hole(
                dossier,
                text if "recherche Jira non exécutée" in text else f"recherche Jira non exécutée : {text}",
            )

    typed_ok = True
    if diagnosis:
        # Une mission « Extraire… » ne demande ni écran ni page de domaine : ne pas les exiger.
        need_page = not extraction or extract.wants_confluence(mission)
        need_screen = not extraction or extract.wants_screen(mission)
        page_ok = bool(dossier.pages) or not need_page
        screen_ok = _has_screen(dossier) or not need_screen
        if not page_ok:
            _hole(dossier, dossier.confluence_note or "page Confluence du domaine absente")
        if not screen_ok:
            _hole(
                dossier,
                "écran du ticket absent (contrôleur qui render, pas un use() incidental)",
            )
        if dossier.typed_ids:
            if any(not str(row.get("role") or "").startswith(":") for row in dossier.typed_ids):
                typed_ok = False
        elif extract.url_uuid_hits("\n".join(dossier.ids) + "\n" + dossier.mission):
            typed_ok = False
            _hole(dossier, "UUID extraits des URL non typés (paramètre de route)")
        if extraction:
            typed_ok = True
        search_ok = (not extract.wants_jira_search(mission)) or (
            dossier.jira_search is not None and not dossier.jira_search.get("error")
        )
        complete = bool(dossier.tickets) and page_ok and screen_ok and typed_ok and search_ok
        dossier.holes_none_ok = complete and not dossier.holes and not dossier.missed
        blocking = (not search_ok) or (not typed_ok) or (not page_ok) or (not screen_ok)
        if blocking and not dossier.holes:
            _hole(dossier, "dossier incomplet pour le diagnostic")
        dossier.ready = complete and not dossier.missed and not dossier.errors
        return

    dossier.ready = not dossier.missed and not dossier.errors


def _hole(dossier: Dossier, text: str) -> None:
    if text and text not in dossier.holes:
        dossier.holes.append(text)


def _has_screen(dossier: Dossier) -> bool:
    for item in dossier.code:
        blob = str(item.get("text") or "")
        if "->render(" in blob or "render(" in blob:
            return True
    return False


def _run_jira_search(config: Config, dossier: Dossier, mission: str, keys: list[str]) -> None:
    if not extract.wants_jira_search(mission):
        return
    jql = extract.build_jql(mission, exclude=keys)
    try:
        packed = jira_provider.search(jql, config.repo_root, limit=5)
    except Exception as error:  # noqa: BLE001
        packed = {"jql": jql, "error": str(error), "results": [], "total": 0}
    err = packed.get("error")
    if err:
        text = str(err)
        packed["error"] = (
            text if "recherche Jira non exécutée" in text else f"recherche Jira non exécutée : {text}"
        )
    packed["jql"] = packed.get("jql") or jql
    dossier.jira_search = packed


def _type_url_uuids(config: Config, dossier: Dossier, blob: str, *, report_holes: bool = True) -> None:
    seen: set[str] = set()
    for slug, value in extract.url_uuid_hits(blob):
        if value in seen:
            continue
        seen.add(value)
        param = _lookup_route_param(config, slug)
        entity, note = extract.entity_for_route_param(param)
        role = f":{param}" if param else f"segment {slug}"
        dossier.typed_ids.append(
            {
                "value": value,
                "role": role,
                "entity": entity,
                "note": note,
            }
        )
        if not param and report_holes:
            _hole(
                dossier,
                f"UUID non typé : {value} (segment URL {slug}, paramètre de route introuvable)",
            )


def _lookup_route_param(config: Config, slug: str) -> str:
    if not slug:
        return ""
    try:
        matches, _total = files.grep(
            config,
            config.repo_root,
            [re.escape(slug)],
            globs=["*.yml", "*.yaml", "*.php", "*.xml"],
            max_matches=12,
            ignore_case=False,
            max_count_per_file=4,
            balance_by_file=True,
        )
    except Exception:  # noqa: BLE001
        return ""
    for match in matches:
        param = extract.route_param_after(slug, str(match.get("text") or ""))
        if param:
            return param
    return ""


def _mark(dossier: Dossier, name: str, started: float) -> None:
    dossier.ledger.phases_s[name] = round(time.monotonic() - started, 2)


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


def _ocr_one(config: Config, dossier: Dossier, path: Path, ocr_dir: Path | None = None) -> None:
    from .. import evidence

    try:
        ocr.read_images(config, None, [str(path)])
        packet = evidence.load(ocr.image_id_for(path))
        transcript = str(packet.get("transcript") or "")
    except Exception as error:  # noqa: BLE001
        dossier.errors.append(f"OCR {path.name}: {error}")
        dossier.holes.append(f"OCR vide : {path.name}")
        dossier.missed.append(f"OCR vide : {path.name}")
        return
    if not transcript.strip():
        dossier.holes.append(f"OCR vide : {path.name}")
        dossier.missed.append(f"OCR vide : {path.name}")
    item = {"name": path.name, "path": str(path), "transcript": transcript[:4000]}
    if ocr_dir is not None and transcript.strip():
        try:
            ocr_dir.mkdir(parents=True, exist_ok=True)
            target = ocr_dir / f"{path.stem}.txt"
            target.write_text(transcript, encoding="utf-8")
            item["ocr_path"] = _relative(config, target)
        except OSError:
            pass
    dossier.images.append(item)
    if path.is_file():
        dossier.ledger.add_image_file(path)
    dossier.ledger.add_text("ocr", transcript)


def _grep_symbol(config: Config, dossier: Dossier, symbol: str, seen_files: set[str]) -> None:
    try:
        matches, total = files.grep(
            config,
            config.repo_root,
            [re.escape(symbol)],
            globs=code_x.CODE_GLOBS,
            max_matches=16,
            ignore_case=False,
            max_count_per_file=6,
            balance_by_file=True,
        )
    except Exception as error:  # noqa: BLE001
        dossier.errors.append(f"rg {symbol}: {error}")
        return
    dossier.rg_counts[symbol] = total
    if total == 0:
        return
    if total > len(matches):
        dossier.sample_based = True
    grouped: dict[str, list[dict]] = {}
    for match in matches:
        relative = str(match.get("file") or "")
        if not relative or relative in seen_files:
            continue
        if code_x.is_noise(str(match.get("text") or "")):
            continue
        grouped.setdefault(relative, []).append(match)
    ranked = sorted(grouped.items(), key=lambda item: code_x.review_rank(item[0]), reverse=True)
    added = 0
    for relative, group in ranked:
        code_x.add_file_from_matches(config, dossier, relative, group, symbol=symbol)
        seen_files.add(relative)
        added += 1
        if added >= 4:
            break
