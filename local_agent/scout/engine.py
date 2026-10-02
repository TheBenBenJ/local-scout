"""Point d'entrée scout : ramasse localement, écrit le dossier, optionnellement synthétise au 9B."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import vision as vision_x
from ..config import Config
from ..mlx import MlxClient, MlxError
from . import extract
from .dossier import Dossier, write_dossier
from .gather import gather

VISION_MAX_IMAGES = 3
VISION_WEAK_OCR_CHARS = 24

SYSTEM_SCOUT = (
    "Tu compiles un dossier pour le diagnostic, tu ne diagnostiques pas. "
    "Classe les extraits déjà présents par thème (handler, flush, contrainte, routing), "
    "avec fichiers:lignes. "
    "Interdiction de conclure à un bug, à une absence, ou de proposer une correction. "
    "Pas de paraphrase des citations déjà dans le dossier. "
    "Français. Texte brut, pas de JSON."
)


@dataclass
class ScoutResult:
    out_dir: Path
    dossier_path: Path
    markdown: str
    raw_chars: int
    visible_chars: int
    visible_chars_deterministic: int
    mlx_used: bool
    mlx_prompt_tokens: int
    mlx_completion_tokens: int
    latency_s: float
    tickets: list[str]
    errors: list[str]
    image_count: int = 0
    ledger: dict = field(default_factory=dict)
    ready: bool = True
    re_read_allowed: list = field(default_factory=list)


def run_scout(
    config: Config,
    mission: str,
    *,
    ticket: str | None = None,
    sources: list[str] | None = None,
    out: str | None = None,
    no_llm: bool = False,
    client: MlxClient | None = None,
) -> ScoutResult:
    slug = extract.slug(mission, ticket)
    out_dir = Path(out).expanduser() if out else (config.repo_root / "temp" / "scout" / slug)
    if not out_dir.is_absolute():
        out_dir = config.repo_root / out_dir
    started = time.monotonic()
    dossier = gather(config, mission, ticket=ticket, sources=sources, out_dir=out_dir)
    visible_deterministic = len(dossier.markdown())
    mlx_started = time.monotonic()
    if not no_llm:
        _maybe_synthesize(config, dossier, client)
        _maybe_vision(config, dossier, client)
    dossier.ledger.phases_s["mlx"] = round(time.monotonic() - mlx_started, 2)
    dossier.latency_s = round(time.monotonic() - started, 2)
    md_path, _json_path = write_dossier(dossier, out_dir)
    markdown = md_path.read_text(encoding="utf-8")
    return ScoutResult(
        out_dir=out_dir,
        dossier_path=md_path,
        markdown=markdown,
        raw_chars=dossier.ledger.text_chars(),
        visible_chars=len(markdown),
        visible_chars_deterministic=visible_deterministic,
        mlx_used=dossier.mlx_used,
        mlx_prompt_tokens=int(dossier.mlx_prompt_tokens),
        mlx_completion_tokens=int(dossier.mlx_completion_tokens),
        latency_s=dossier.latency_s,
        tickets=[str(item.get("key") or "") for item in dossier.tickets if item.get("key")],
        errors=list(dossier.errors),
        image_count=len(dossier.images),
        ledger=dossier.ledger.as_dict(),
        ready=bool(dossier.ready),
        re_read_allowed=list(dossier.re_read_allowed),
    )


def _maybe_synthesize(config: Config, dossier: Dossier, client: MlxClient | None) -> None:
    client = client or MlxClient(config)
    try:
        client.models()
    except MlxError:
        dossier.errors.append("LLM local injoignable : dossier déterministe seulement.")
        return
    sketch = dossier.markdown(cap=8000)
    prompt = (
        "Mission:\n"
        f"{dossier.mission}\n\n"
        "Preuves déjà extraites (ne pas les recopier) :\n"
        f"{sketch}\n\n"
        "Rédige uniquement la synthèse locale, 3 à 6 phrases."
    )
    try:
        completion = client.complete(prompt, SYSTEM_SCOUT, max_tokens=min(400, config.max_completion_tokens))
    except (MlxError, TypeError, AttributeError):
        dossier.errors.append("Synthèse locale échouée : garder le dossier brut.")
        return
    dossier.mlx_used = True
    dossier.mlx_prompt_tokens = int(completion.prompt_tokens or 0)
    dossier.mlx_completion_tokens = int(completion.completion_tokens or 0)
    dossier.synthesis = (completion.text or "").strip()[:1200]


def _vision_capable(client: object) -> bool:
    checker = getattr(client, "supports_vision", None)
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except MlxError:
        return False


def _needs_vision(mission: str, transcript: str) -> bool:
    """OCR seul ne suffit pas : trou de layout (indice dans la mission) ou transcript trop maigre."""
    if vision_x.VISION_HINTS.search(mission or ""):
        return True
    return len((transcript or "").strip()) < VISION_WEAK_OCR_CHARS


def _maybe_vision(config: Config, dossier: Dossier, client: MlxClient | None) -> None:
    """Seconde passe vision sur les captures dont l'OCR seul ne suffit pas. Jamais le brut en dur."""
    if not dossier.images:
        return
    client = client or MlxClient(config)
    try:
        client.models()
    except MlxError:
        return
    if not _vision_capable(client):
        return
    applied = 0
    for item in dossier.images:
        if applied >= VISION_MAX_IMAGES:
            break
        transcript = str(item.get("transcript") or "")
        if not _needs_vision(dossier.mission, transcript):
            continue
        path = Path(str(item.get("path") or ""))
        if not path.is_file():
            continue
        try:
            result = vision_x.reason(config, client, path, transcript, dossier.mission)
        except Exception:  # noqa: BLE001 - une capture illisible ne doit pas casser le dossier
            continue
        if result.get("vision") != "applied":
            continue
        item["vision_notes"] = result.get("notes") or []
        item["vision_ui"] = result.get("ui") or []
        item["vision_headers"] = result.get("header_split") or []
        applied += 1
