"""Dossier borné : le seul texte destiné à l'orchestrateur."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .stats import SourceLedger
from . import extract
from . import pdf as pdf_x

DOSSIER_MAX_CHARS = 12_000

_TAIL_READY = (
    "## À l'orchestrateur\n"
    "- Trancher le diagnostic et la qualification.\n"
    "- Mesurer encore : SQL, grep, rejeu.\n"
    "- Relire seulement les paths marqués tronqués ou les ids demandés en drill-down.\n"
    "- Ne pas relire le brut déjà intégral.\n"
    "- Vérifier au grep les comptages et les conclusions d'absence.\n"
)
_TAIL_MISSED = (
    "## À l'orchestrateur\n"
    "- Mission non couverte : voir **Trous** et re-read_allowed.\n"
    "- Mesurer encore : SQL, grep, rejeu.\n"
    "- Ne pas diagnostiquer comme si les sources étaient extraites.\n"
)


@dataclass
class _Section:
    name: str
    heading: str
    items: list[str]
    reserve: int
    floor: int
    priority: int


@dataclass
class Dossier:
    mission: str
    tickets: list[dict] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    code: list[dict] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    holes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    truncated_sources: list[dict] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    rg_counts: dict = field(default_factory=dict)
    sample_based: bool = False
    absence_guard: bool = False
    excerpt_seq: int = 0
    annots: list[dict] = field(default_factory=list)
    indexes: list[dict] = field(default_factory=list)
    logs: list[dict] = field(default_factory=list)
    branches: list[dict] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    re_read_allowed: list[dict] = field(default_factory=list)
    read_sources: list[str] = field(default_factory=list)
    ready: bool = True
    incidental: list[str] = field(default_factory=list)
    typed_ids: list[dict] = field(default_factory=list)
    jira_search: dict | None = None
    primary_key: str = ""
    confluence_note: str = ""
    holes_none_ok: bool = False
    synthesis: str = ""
    raw_chars: int = 0
    mlx_used: bool = False
    mlx_prompt_tokens: int = 0
    mlx_completion_tokens: int = 0
    latency_s: float = 0.0
    ledger: SourceLedger = field(default_factory=SourceLedger)

    def allow_reread(self, path: str, reason: str) -> None:
        for item in self.re_read_allowed:
            if item.get("path") == path:
                return
        self.re_read_allowed.append({"path": path, "reason": reason})

    def markdown(self, *, cap: int = DOSSIER_MAX_CHARS) -> str:
        primary = [item for item in self.tickets if item.get("role") != "linked"]
        linked = [item for item in self.tickets if item.get("role") == "linked"]
        if not primary and self.tickets:
            primary = list(self.tickets)
            linked = []
        sections = [
            _Section("mission", "## Mission", [_mission_line(self.mission)], 400, 80, 2),
        ]
        if primary:
            primary_item = dict(primary[0], mission=self.mission)
            ticket_text, ticket_cuts = _ticket_block(primary_item, typed=self.typed_ids)
            if ticket_cuts:
                key = primary_item.get("key") or ""
                self.allow_reread(
                    f"jira://{key}" if key else "ticket",
                    "tronquée à l'affichage : "
                    + ", ".join(ticket_cuts)
                    + (
                        f" ; texte intégral sur disque : {primary_item.get('full_path')}"
                        if primary_item.get("full_path")
                        else " ; recharger seulement ces parties"
                    ),
                )
            sections.append(_Section("ticket", "## Ticket", [ticket_text], 5000, 180, 1))
        if self.images:
            sections.append(
                _Section(
                    "images",
                    "## Captures",
                    [_image_block(item) for item in self.images],
                    3600,
                    120,
                    2,
                )
            )
        if linked:
            sections.append(
                _Section(
                    "linked",
                    "## Tickets liés demandés",
                    [_linked_ticket_block(item) for item in linked],
                    800,
                    140,
                    2,
                )
            )
        if self.jira_search is not None:
            sections.append(
                _Section("jql", "## Recherche Jira", [_jira_search_block(self.jira_search)], 700, 120, 1)
            )
        code_items = [_code_block(item) for item in self.code[:3]]
        code_items.extend(self.incidental[:4])
        if code_items:
            sections.append(_Section("code", "## Code", code_items, 1600, 200, 2))
        if self.pages:
            sections.append(
                _Section("pages", "## Confluence", self._page_items(), 4000, 100, 2)
            )
        elif self.confluence_note:
            sections.append(
                _Section("pages", "## Confluence", [self.confluence_note], 200, 40, 2)
            )
        if self.annots:
            sections.append(
                _Section(
                    "annots",
                    "## Annots PDF",
                    [pdf_x.render_annot(item, excerpt_id=str(item.get("id") or "")) for item in self.annots],
                    2400,
                    280,
                    1,
                )
            )
        if self.logs:
            sections.append(
                _Section("logs", "## Logs", [_log_block(item) for item in self.logs], 2400, 300, 1)
            )
        if self.branches:
            sections.append(
                _Section(
                    "branches",
                    "## Branches",
                    [_branch_block(item) for item in self.branches],
                    1200,
                    200,
                    2,
                )
            )
        if self.indexes:
            sections.append(
                _Section(
                    "indexes",
                    "## Index dossiers",
                    [
                        f"### `{item.get('path')}`\n" + "\n".join(item.get("entries") or [])
                        for item in self.indexes
                    ],
                    800,
                    120,
                    2,
                )
            )
        if self.synthesis.strip():
            sections.append(
                _Section(
                    "synthesis",
                    "## Synthèse locale (indicatif, à recouper)",
                    [self.synthesis.strip()],
                    300,
                    0,
                    8,
                )
            )
        holes = list(self.holes) + list(self.missed)
        if holes:
            sections.append(_Section("holes", "## Trous", [f"- {hole}" for hole in holes], 500, 120, 1))
        elif self.holes_none_ok:
            sections.append(_Section("holes", "## Trous", ["- aucun"], 80, 40, 1))
        if self.errors:
            sections.append(
                _Section(
                    "errors",
                    "## Erreurs de chargement",
                    [f"- {error}" for error in self.errors],
                    220,
                    60,
                    1,
                )
            )
        if self.locations and not self.typed_ids:
            sections.append(
                _Section("locations", "## Locations", [f"- {item}" for item in self.locations], 300, 60, 2)
            )
        return _pack(_header(self), sections, _tail(self), cap)

    def _page_items(self) -> list[str]:
        items = []
        for item in self.pages[:2]:
            text, cut = _page_block(item)
            if cut:
                page_id = item.get("id") or item.get("page") or ""
                reason = "corps tronqué à l'affichage"
                if item.get("full_path"):
                    reason += f" ; texte intégral sur disque : {item.get('full_path')}"
                self.allow_reread(f"confluence://{page_id}", reason)
            items.append(text)
        return items

    def to_json(self) -> dict:
        return {
            "mission": self.mission,
            "tickets": self.tickets,
            "pages": self.pages,
            "images": [
                {
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "chars": len(item.get("transcript") or ""),
                }
                for item in self.images
            ],
            "code": self.code,
            "ids": self.ids,
            "holes": self.holes,
            "errors": self.errors,
            "truncated_sources": self.truncated_sources,
            "locations": self.locations,
            "rg_counts": self.rg_counts,
            "sample_based": self.sample_based,
            "ready": self.ready,
            "missed": self.missed,
            "re_read_allowed": self.re_read_allowed,
            "read_sources": self.read_sources,
            "annots": [
                {
                    "file": item.get("file"),
                    "subtype": item.get("subtype"),
                    "page": item.get("page"),
                    "author": item.get("author"),
                    "contents": item.get("contents"),
                }
                for item in self.annots
            ],
            "logs": self.logs,
            "branches": self.branches,
            "synthesis": self.synthesis,
            "mlx_used": self.mlx_used,
            "mlx_prompt_tokens": self.mlx_prompt_tokens,
            "mlx_completion_tokens": self.mlx_completion_tokens,
            "raw_chars": self.ledger.text_chars(),
            "visible_chars": 0,
            "latency_s": self.latency_s,
            "ledger": self.ledger.as_dict(),
        }


def _header(dossier: Dossier) -> str:
    lines = ["# Dossier scout"]
    if dossier.sample_based:
        lines.append("Réponse établie sur un échantillon.")
    if dossier.absence_guard or dossier.locations:
        locs = "; ".join(dossier.locations[:8]) if dossier.locations else "voir Locations"
        lines.append(f"Ne pas conclure à l'absence. Locations : {locs}")
    if dossier.re_read_allowed:
        lines.append("re-read_allowed:")
        for item in dossier.re_read_allowed[:12]:
            lines.append(f"- `{item.get('path')}` : {item.get('reason')}")
        lines.append(
            "« Ne pas relire » ne s'applique qu'aux sources dont l'extrait est complet pour la mission."
        )
    elif dossier.ready:
        lines.append(
            "Diagnostiquer depuis ce dossier. Relire seulement les paths marqués tronqués "
            "ou les ids demandés en drill-down. Ne pas relire le brut déjà intégral."
        )
    else:
        lines.append("Mission non couverte : voir **Trous**. Ne pas relire n'est pas autorisé.")
    if dossier.truncated_sources:
        lines.append("Sources tronquées, l'orchestrateur peut Relire path:offset sur ces ids.")
        for item in dossier.truncated_sources[:8]:
            ids = ", ".join(str(name) for name in (item.get("ids") or []))
            lines.append(
                f"- `{item.get('path')}` : {item.get('kept_lines')}/{item.get('total_lines')} lignes, "
                f"{item.get('kept_bytes')}/{item.get('total_bytes')} octets, extraits {ids}"
            )
    return "\n".join(lines) + "\n"


def _tail(dossier: Dossier) -> str:
    return _TAIL_READY if dossier.ready else _TAIL_MISSED


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _mission_line(text: str) -> str:
    raw = (text or "").strip() or "(vide)"
    for sep in (". ", ".\n", " : ", "\n"):
        if sep in raw:
            raw = raw.split(sep, 1)[0].strip()
            break
    return raw[:220]


TICKET_BODY_CHARS = 3500
TICKET_BODY_LINES = 60
TICKET_FIELD_CHARS = 1200
TICKET_OTHER_FIELDS = 4
TICKET_OTHER_FIELD_CHARS = 400
TICKET_COMMENTS = 6
TICKET_COMMENT_CHARS = 700


def _ticket_block(item: dict, typed: list[dict] | None = None) -> tuple[str, list[str]]:
    """Rend le ticket et la liste de ce qui a été coupé (vide = rien à relire)."""
    key = item.get("key") or "?"
    goal = item.get("goal") or ""
    status = item.get("status") or ""
    itype = item.get("issuetype") or ""
    versions = ", ".join(item.get("fix_versions") or [])
    cuts: list[str] = []
    body, focus_truncated = extract.ticket_focus(
        item.get("acceptance_criteria_verbatim") or "", limit=TICKET_BODY_CHARS
    )
    full_lines = [line for line in body.splitlines() if line.strip()]
    body_lines = full_lines[:TICKET_BODY_LINES]
    if focus_truncated or len(full_lines) > len(body_lines):
        cuts.append("description")
    head = f"Type : {itype} · Statut : {status}"
    if item.get("priority"):
        head += f" · Priorité : {item.get('priority')}"
    if versions:
        head += f" · MEP : {versions}"
    lines = [f"### {key} — {goal}", head, "", *body_lines]
    mission = str(item.get("mission") or "").lower()
    fields = list(item.get("custom_fields") or [])
    asked = [field for field in fields if str(field.get("name") or "").lower() in mission]
    others = [field for field in fields if field not in asked][:TICKET_OTHER_FIELDS]
    for field in asked + others:
        text = str(field.get("text") or "").strip()
        if not text:
            continue
        limit = TICKET_FIELD_CHARS if field in asked else TICKET_OTHER_FIELD_CHARS
        if len(text) > limit:
            cuts.append(f"champ {field.get('name')}")
        lines.extend(["", f"**{field.get('name')}** : {_clip(text, limit)}"])
    for name in item.get("asked_empty_fields") or []:
        lines.extend(["", f"**{name}** : vide dans Jira."])
    links = item.get("links") or []
    if links:
        lines.append("")
        lines.append(
            "Liens : "
            + " ; ".join(
                f"{link.get('key')} ({link.get('relation')}, {link.get('status')}) {link.get('goal')}".strip()
                for link in links
            )
        )
    attachments = [str(name) for name in (item.get("attachments") or []) if name]
    if attachments:
        unread = [name for name in attachments if not extract.is_image_path(name)]
        line = f"Pièces jointes ({len(attachments)}) : " + ", ".join(attachments[:12])
        if unread:
            line += " — non lues par scout : " + ", ".join(unread[:6])
        if item.get("pieces_dir"):
            line += f" — images déjà enregistrées sous `{item.get('pieces_dir')}`"
        lines.extend(["", line])
    if item.get("show_comments"):
        comments = list(item.get("comments") or [])
        total = int(item.get("comment_total") or len(comments))
        shown = comments[-int(item.get("comment_limit") or TICKET_COMMENTS):]
        if shown:
            lines.extend(["", f"Commentaires ({len(shown)} derniers sur {total}) :"])
            for comment in shown:
                text = " ".join(str(comment.get("body") or "").split())
                if len(text) > TICKET_COMMENT_CHARS:
                    cuts.append("commentaires")
                lines.append(
                    f"- {comment.get('created')} {comment.get('author')} : {_clip(text, TICKET_COMMENT_CHARS)}"
                )
            if total > len(shown):
                cuts.append("commentaires")
        elif total == 0:
            lines.extend(["", "Commentaires : aucun."])
    if typed:
        lines.append("")
        lines.append("UUID typés :")
        for row in typed[:8]:
            extra = f" — {row.get('note')}" if row.get("note") else ""
            lines.append(
                f"- `{row.get('value')}` | {row.get('role') or 'segment inconnu'} | "
                f"{row.get('entity') or '?'}{extra}"
            )
    return "\n".join(lines).rstrip(), list(dict.fromkeys(cuts))


def _linked_ticket_block(item: dict) -> str:
    key = item.get("key") or "?"
    goal = item.get("goal") or ""
    status = item.get("status") or ""
    versions = ", ".join(item.get("fix_versions") or [])
    body_lines = [
        line for line in (item.get("acceptance_criteria_verbatim") or "").splitlines() if line.strip()
    ][:5]
    lines = [
        f"### {key} — {goal}",
        f"Statut : {status}" + (f" · fixVersions : {versions}" if versions else ""),
        *body_lines,
    ]
    return "\n".join(lines).rstrip()


def _jira_search_block(item: dict) -> str:
    jql = item.get("jql") or ""
    error = item.get("error")
    results = item.get("results") or []
    total = item.get("total")
    lines = [f"JQL : `{jql}`"]
    if error:
        lines.append(f"non exécutée : {error}" if "non exécutée" not in str(error) else str(error))
        return "\n".join(lines)
    lines.append(f"N résultats (API) : {total if total is not None else len(results)} — 5 candidats max.")
    for row in results[:5]:
        lines.append(
            f"- {row.get('key')} — {row.get('goal')} · {row.get('status')} · {row.get('issuetype')}"
        )
    if not results:
        lines.append("0 candidat. Ne pas conclure à l'absence sans recouper le JQL.")
    return "\n".join(lines)


PAGE_BODY_CHARS = 3500


def _page_block(item: dict) -> tuple[str, bool]:
    """Page chargée : corps dans le budget. Résultat de recherche : citation courte (candidat)."""
    title = item.get("title") or item.get("page") or "?"
    page_id = item.get("id") or item.get("page") or ""
    header = f"### {title}"
    if page_id:
        header += f" · pageId {page_id}"
    if item.get("quote") and not item.get("body"):
        return f"{header}\n\n{_clip(item.get('quote') or '', 400)}", False
    body = str(item.get("body") or item.get("text") or "").strip()
    cut = len(body) > PAGE_BODY_CHARS
    return f"{header}\n\n{_clip(body, PAGE_BODY_CHARS)}", cut


def _image_block(item: dict) -> str:
    name = item.get("name") or item.get("path") or "image"
    table = (item.get("table") or "").strip()
    cut = False
    if not table:
        table, cut = _ocr_text(item.get("transcript") or "")
    lines = [f"### {name}", table or "OCR inutilisable"]
    if cut and item.get("ocr_path"):
        lines.append(f"OCR coupé ici ; transcript complet (texte, pas l'image) : `{item.get('ocr_path')}`")
    if item.get("noisy", True) or table == "OCR inutilisable":
        lines.append("OCR bruit, ne pas citer les tokens incertains.")
    notes = list(item.get("vision_notes") or [])
    ui = list(item.get("vision_ui") or [])
    headers = list(item.get("vision_headers") or [])
    if notes or ui or headers:
        lines.append("Vision locale (layout seulement ; l'OCR reste la source pour les nombres) :")
        lines.extend(f"- {note}" for note in notes[:6])
        lines.extend(f"- UI : {entry}" for entry in ui[:6])
        if headers:
            lines.append("- En-têtes : " + " | ".join(headers[:12]))
    return "\n".join(lines)


OCR_IMAGE_CHARS = 1000
OCR_IMAGE_LINES = 30


def _ocr_text(transcript: str, *, limit: int = OCR_IMAGE_CHARS) -> tuple[str, bool]:
    """Transcript dans l'ordre de lecture, cellules vides retirées. Aucun tri par mots-clés."""
    kept: list[str] = []
    for raw in (transcript or "").splitlines():
        line = raw.strip()
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            cells = [cell for cell in cells if cell and not set(cell) <= set("-: ")]
            line = " | ".join(cells)
        if not line or (kept and kept[-1] == line):
            continue
        kept.append(line)
    text = "\n".join(kept[:OCR_IMAGE_LINES])
    cut = len(kept) > OCR_IMAGE_LINES or len(text) > limit
    if len(text) > limit:
        text = text[:limit].rsplit("\n", 1)[0] if "\n" in text[:limit] else text[:limit]
    return (text or "OCR inutilisable"), cut


def _code_block(item: dict) -> str:
    loc = item.get("location") or item.get("file") or ""
    excerpt_id = item.get("id") or ""
    text = "\n".join((item.get("text") or "").strip().splitlines()[:15])[:1600]
    prefix = f"`{loc}`"
    if excerpt_id:
        prefix += f" [{excerpt_id}]"
    if item.get("truncated"):
        prefix += (
            f" tronqué {item.get('kept_lines')}/{item.get('total_lines')} lignes"
        )
    lines = [prefix]
    if text:
        lines.append(f"```\n{text}\n```")
    return "\n".join(lines)


def _log_block(item: dict) -> str:
    label = item.get("label") or "log"
    kept = (item.get("kept") or "").strip()
    matches = item.get("match_count") or 0
    header = f"### `{label}`"
    if matches:
        header += f" · {matches} signal(aux) d'échec"
    else:
        header += " · aucun signal d'échec, queue rendue"
    if item.get("truncated"):
        header += f" · tronqué {item.get('kept_lines')}/{item.get('total_lines')} lignes"
    body = kept or "(vide)"
    return f"{header}\n\n```\n{body}\n```"


def _branch_block(item: dict) -> str:
    pattern = item.get("pattern") or "?"
    error = item.get("error")
    if error:
        return f"### `git://{pattern}`\n\nnon exécutée : {error}"
    mains = ", ".join(item.get("main_branches") or []) or "(aucune détectée)"
    lines = [
        f"### `git://{pattern}` — {item.get('commit_matches', 0)} commit(s) au message, "
        f"branches principales : {mains}"
    ]
    main_set = set(item.get("main_branches") or [])
    for branch in item.get("branches") or []:
        if branch.get("branch") in main_set:
            merged = "branche principale"
        else:
            merged = ", ".join(branch.get("merged_into") or []) or "non fusionnée"
        via = "/".join(
            part
            for part, flag in (("nom", branch.get("matched_name")), ("historique", branch.get("matched_history")))
            if flag
        ) or "?"
        lines.append(
            f"- `{branch.get('branch')}` — {branch.get('tip') or '?'} · "
            f"fusionnée dans : {merged} · trouvée par : {via}"
        )
    if not item.get("branches"):
        lines.append("- 0 branche candidate.")
    return "\n".join(lines)


def _items_text(items: list[str]) -> str:
    return "\n".join(item.rstrip() for item in items if item.strip())


def _truncate_items(items: list[str], budget: int) -> str:
    if budget <= 0 or not items:
        return ""
    kept: list[str] = []
    used = 0
    for index, raw in enumerate(items):
        item = raw.rstrip()
        sep = 1 if kept else 0
        if used + sep + len(item) <= budget:
            kept.append(item)
            used += sep + len(item)
            continue
        remaining = len(items) - index
        omitted = f"[{remaining} additional items omitted]"
        room = budget - used - sep
        if room >= 40:
            more = len(items) - index - 1
            extra = f"\n[{more} additional items omitted]" if more else ""
            take = room - len("[truncated]") - 1 - len(extra)
            if take >= 12:
                kept.append(item[:take].rstrip() + "\n[truncated]" + extra)
            elif remaining:
                kept.append(omitted[:room] if room < len(omitted) else omitted)
        elif remaining and used + sep + len(omitted) <= budget:
            kept.append(omitted)
        break
    text = "\n".join(kept)
    if len(text) > budget:
        cut = max(0, budget - 12)
        text = text[:cut].rstrip() + "\n[truncated]"
    return text


def _render(header: str, sections: list[tuple[_Section, str]], tail: str) -> str:
    parts = [header.rstrip(), ""]
    for section, body in sections:
        body = body.rstrip()
        if not body:
            continue
        parts.append(section.heading)
        parts.append(body)
        parts.append("")
    parts.append(tail.rstrip())
    parts.append("")
    return "\n".join(parts)


def _pack(header: str, sections: list[_Section], tail: str, cap: int) -> str:
    sections = [section for section in sections if any(item.strip() for item in section.items)]
    header = header if header.endswith("\n") else header + "\n"
    tail = tail if tail.endswith("\n") else tail + "\n"
    actual = [_items_text(section.items) for section in sections]
    heading_cost = [len(section.heading) + 2 for section in sections]
    n = len(sections)
    seps = 2 + n
    fixed = len(header.rstrip()) + 1 + len(tail.rstrip()) + 1 + seps
    budget = cap - fixed - sum(heading_cost)
    if budget < 40:
        text = _render(header, list(zip(sections, actual)), tail)
        if len(text) <= cap:
            return text
        return text[: max(0, cap - 12)].rstrip() + "\n[truncated]\n"

    alloc = [min(len(text), section.floor) for text, section in zip(actual, sections)]
    leftover = budget - sum(alloc)
    order = sorted(range(n), key=lambda index: sections[index].priority)
    if leftover < 0:
        for index in reversed(order):
            reducible = alloc[index] - min(len(actual[index]), max(0, sections[index].floor // 2))
            if reducible <= 0:
                continue
            take = min(reducible, -leftover)
            alloc[index] -= take
            leftover += take
            if leftover >= 0:
                break
        leftover = max(0, leftover)

    for index in order:
        want = min(len(actual[index]), sections[index].reserve) - alloc[index]
        if want <= 0 or leftover <= 0:
            continue
        give = min(want, leftover)
        alloc[index] += give
        leftover -= give
    for index in order:
        want = len(actual[index]) - alloc[index]
        if want <= 0 or leftover <= 0:
            continue
        give = min(want, leftover)
        alloc[index] += give
        leftover -= give

    packed: list[tuple[_Section, str]] = []
    for section, text, size in zip(sections, actual, alloc):
        body = text if len(text) <= size else _truncate_items(section.items, size)
        packed.append((section, body))
    text = _render(header, packed, tail)
    if len(text) <= cap:
        return text
    overflow = len(text) - cap
    for index in reversed(order):
        if overflow <= 0:
            break
        reducible = alloc[index] - sections[index].floor
        if reducible <= 0:
            continue
        cut = min(reducible, overflow + 16)
        alloc[index] -= cut
        overflow -= cut
        packed[index] = (sections[index], _truncate_items(sections[index].items, alloc[index]))
    text = _render(header, packed, tail)
    if len(text) <= cap:
        return text
    return text[: max(0, cap - 12)].rstrip() + "\n[truncated]\n"


def write_dossier(dossier: Dossier, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = dossier.markdown()
    if "[truncated]" in markdown or "additional items omitted" in markdown:
        dossier.sample_based = True
        markdown = dossier.markdown()
    payload = dossier.to_json()
    payload["visible_chars"] = len(markdown)
    payload["raw_chars"] = dossier.ledger.text_chars()
    md_path = out_dir / "dossier.md"
    json_path = out_dir / "dossier.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return md_path, json_path
