"""Dossier borné : le seul texte destiné à l'orchestrateur."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .stats import SourceLedger

DOSSIER_MAX_CHARS = 12_000


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
        parts = [
            "# Dossier scout — prêt pour le diagnostic",
            "",
            "Contexte délimité localement. Ne pas relire Jira, Confluence, captures ni l'arbre.",
            "Diagnostiquer, qualifier, rédiger : à l'orchestrateur. Les faits ci-dessous sont extraits, pas tranchés.",
            "",
            "## Mission",
            (self.mission or "").strip() or "(vide)",
            "",
        ]
        image_clip = _image_clip(len(self.images))
        ticket_body_clip, comment_clip, comment_keep = _ticket_budget(bool(self.images))
        if self.synthesis:
            parts += ["## Synthèse locale (indicatif, à recouper)", "", self.synthesis.strip(), ""]
        if self.images:
            parts += ["## Captures (OCR)", ""]
            for item in self.images:
                parts.append(_image_block(item, clip=image_clip))
        if self.tickets:
            parts += ["## Tickets", ""]
            for item in self.tickets:
                parts.append(_ticket_block(item, body_clip=ticket_body_clip, comment_clip=comment_clip, comment_keep=comment_keep))
        if self.pages:
            parts += ["## Confluence", ""]
            for item in self.pages:
                parts.append(_page_block(item))
        if self.code:
            parts += ["## Code", ""]
            for item in self.code:
                loc = item.get("location") or item.get("file") or ""
                text = (item.get("text") or "").strip()
                parts.append(f"`{loc}`")
                if text:
                    parts.append(f"```\n{text[:500]}\n```")
                parts.append("")
        if self.ids:
            parts += ["## Identifiants déjà fournis (ne pas les chercher ailleurs)", ""]
            parts.append(", ".join(self.ids))
            parts.append("")
        parts += ["## Trous", ""]
        parts.extend(f"- {hole}" for hole in (self.holes or ["aucun annoncé"]))
        parts.append("")
        if self.errors:
            parts += ["## Erreurs de chargement", ""]
            parts.extend(f"- {error}" for error in self.errors)
            parts.append("")
        parts += [
            "## À l'orchestrateur",
            "- Trancher le diagnostic et la qualification.",
            "- Ne pas relancer un chargement des sources déjà listées.",
            "- Vérifier au grep les comptages et les conclusions d'absence.",
            "",
        ]
        text = "\n".join(parts).strip() + "\n"
        if len(text) <= cap:
            return text
        keep = cap - 80
        return text[:keep].rstrip() + "\n\n[dossier tronqué à %s caractères]\n" % cap

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


def _image_clip(count: int) -> int:
    if count <= 0:
        return 1600
    if count == 1:
        return 1600
    if count == 2:
        return 1200
    if count == 3:
        return 1000
    return 850


def _ticket_budget(has_images: bool) -> tuple[int, int, int]:
    if has_images:
        return 1100, 320, 4
    return 1800, 700, 8


def _ticket_block(
    item: dict,
    *,
    body_clip: int = 1800,
    comment_clip: int = 700,
    comment_keep: int = 8,
) -> str:
    key = item.get("key") or "?"
    goal = item.get("goal") or ""
    status = item.get("status") or ""
    itype = item.get("issuetype") or ""
    body = _clip(item.get("acceptance_criteria_verbatim") or "", body_clip)
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
        for comment in comments[-comment_keep:]:
            author = comment.get("author") or ""
            created = comment.get("created") or ""
            lines.append(f"- {created} {author}: {_clip(comment.get('body') or '', comment_clip)}")
        lines.append("")
    atts = item.get("attachments") or []
    if atts:
        lines.append("Pièces : " + ", ".join(str(name) for name in atts[:12]))
        lines.append("")
    return "\n".join(lines)


def _page_block(item: dict) -> str:
    title = item.get("title") or item.get("page") or "?"
    body = _clip(item.get("body") or item.get("text") or "", 2000)
    return f"### {title}\n\n{body}\n"


def _image_block(item: dict, *, clip: int = 1600) -> str:
    name = item.get("name") or item.get("path") or "image"
    transcript = _clip(item.get("transcript") or "", clip)
    return f"### {name}\n\n{transcript}\n"


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
