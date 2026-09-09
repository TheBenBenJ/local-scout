"""Dossier borné : le seul texte destiné à l'orchestrateur."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .stats import SourceLedger

DOSSIER_MAX_CHARS = 12_000

_HEADER = (
    "# Dossier scout\n"
    "Ne pas relire les sources listées. Diagnostiquer à partir de ce texte.\n"
)
_TAIL = (
    "## À l'orchestrateur\n"
    "- Trancher le diagnostic et la qualification.\n"
    "- Ne pas relancer un chargement des sources déjà listées.\n"
    "- Vérifier au grep les comptages et les conclusions d'absence.\n"
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
    synthesis: str = ""
    raw_chars: int = 0
    mlx_used: bool = False
    mlx_prompt_tokens: int = 0
    mlx_completion_tokens: int = 0
    latency_s: float = 0.0
    ledger: SourceLedger = field(default_factory=SourceLedger)

    def markdown(self, *, cap: int = DOSSIER_MAX_CHARS) -> str:
        sections = [
            _Section("mission", "## Mission", [(self.mission or "").strip() or "(vide)"], 500, 120, 3),
        ]
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
        if self.images:
            sections.append(
                _Section(
                    "images",
                    "## Captures (OCR)",
                    [_image_block(item) for item in self.images],
                    1000,
                    160,
                    5,
                )
            )
        if self.tickets:
            sections.append(
                _Section(
                    "tickets",
                    "## Tickets",
                    [_ticket_block(item) for item in self.tickets],
                    1400,
                    220,
                    4,
                )
            )
        if self.pages:
            sections.append(
                _Section(
                    "pages",
                    "## Confluence",
                    [_page_block(item) for item in self.pages],
                    900,
                    140,
                    6,
                )
            )
        if self.code:
            sections.append(
                _Section(
                    "code",
                    "## Code",
                    [_code_block(item) for item in self.code],
                    1800,
                    280,
                    2,
                )
            )
        if self.ids:
            sections.append(
                _Section(
                    "ids",
                    "## Identifiants déjà fournis (ne pas les chercher ailleurs)",
                    [", ".join(self.ids)],
                    80,
                    0,
                    7,
                )
            )
        sections.append(
            _Section(
                "holes",
                "## Trous",
                [f"- {hole}" for hole in (self.holes or ["aucun annoncé"])],
                350,
                80,
                1,
            )
        )
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
        return _pack(_HEADER, sections, _TAIL, cap)

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
            "synthesis": self.synthesis,
            "mlx_used": self.mlx_used,
            "mlx_prompt_tokens": self.mlx_prompt_tokens,
            "mlx_completion_tokens": self.mlx_completion_tokens,
            "raw_chars": self.ledger.text_chars(),
            "visible_chars": 0,
            "latency_s": self.latency_s,
            "ledger": self.ledger.as_dict(),
        }


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _ticket_block(item: dict) -> str:
    key = item.get("key") or "?"
    goal = item.get("goal") or ""
    status = item.get("status") or ""
    itype = item.get("issuetype") or ""
    body = _clip(item.get("acceptance_criteria_verbatim") or "", 2500)
    comments = item.get("comments") or []
    lines = [
        f"### {key} — {goal}",
        f"Type : {itype} · Statut : {status}",
        "",
        body,
        "",
    ]
    if comments:
        lines.append("Commentaires (plus récents) :")
        for comment in comments[-4:]:
            author = comment.get("author") or ""
            created = comment.get("created") or ""
            lines.append(f"- {created} {author}: {_clip(comment.get('body') or '', 400)}")
        lines.append("")
    atts = item.get("attachments") or []
    if atts:
        lines.append("Pièces : " + ", ".join(str(name) for name in atts[:12]))
        lines.append("")
    return "\n".join(lines).rstrip()


def _page_block(item: dict) -> str:
    title = item.get("title") or item.get("page") or "?"
    body = _clip(item.get("body") or item.get("text") or "", 2500)
    return f"### {title}\n\n{body}"


def _image_block(item: dict) -> str:
    name = item.get("name") or item.get("path") or "image"
    transcript = _clip(item.get("transcript") or "", 2000)
    return f"### {name}\n\n{transcript}"


def _code_block(item: dict) -> str:
    loc = item.get("location") or item.get("file") or ""
    text = (item.get("text") or "").strip()[:1200]
    lines = [f"`{loc}`"]
    if text:
        lines.append(f"```\n{text}\n```")
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
    payload = dossier.to_json()
    payload["visible_chars"] = len(markdown)
    payload["raw_chars"] = dossier.ledger.text_chars()
    md_path = out_dir / "dossier.md"
    json_path = out_dir / "dossier.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return md_path, json_path
