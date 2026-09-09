"""Harnais de mesure scout. Colonnes séparées : 9B, dossier, PNG, Cursor (vide)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ..budget import tokens_from_chars
from ..config import Config, get_config
from ..files import GuardrailError
from ..mlx import MlxClient, MlxError
from .engine import ScoutResult, run_scout
from .compare import compare_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-scout bench",
        description="Mesure locale du scout. N'invente pas de cartes Cursor.",
    )
    parser.add_argument("--ticket", required=True, help="LYSI-XXXX")
    parser.add_argument("--mission", default="", help="mission passée au scout")
    parser.add_argument("--out", default="temp/scout/bench", help="dossier de sortie")
    parser.add_argument("--no-llm", action="store_true", help="sans synthèse 9B")
    parser.add_argument(
        "--compare-nolm",
        action="store_true",
        help="second run --no-llm (double fetch Jira). Inutile : visible_chars_deterministic est déjà dans le run.",
    )
    return parser


def result_payload(result: ScoutResult) -> dict:
    ledger = result.ledger or {}
    visible = result.visible_chars
    return {
        "path": str(result.dossier_path),
        "tickets": result.tickets,
        "errors": result.errors,
        "local": {
            "latency_s": result.latency_s,
            "mlx_used": result.mlx_used,
            "mlx_prompt_tokens": result.mlx_prompt_tokens,
            "mlx_completion_tokens": result.mlx_completion_tokens,
            "phases_s": ledger.get("phases_s") or {},
        },
        "dossier": {
            "visible_chars": visible,
            "visible_tokens_est": tokens_from_chars(visible),
            "visible_chars_deterministic": result.visible_chars_deterministic,
            "visible_tokens_deterministic_est": tokens_from_chars(result.visible_chars_deterministic),
        },
        "sources": ledger,
        "png": {
            "count": result.image_count,
            "bytes": int(ledger.get("image_bytes") or 0),
            "on_disk": True,
        },
        "cursor": {
            "before_total": None,
            "after_total": None,
            "delta": None,
            "note": "Ce chat de mesure CLI n'a pas de cartes Usage. Ne pas inventer.",
        },
        "paths": compare_paths(result),
    }


def render_markdown(ticket: str, payload: dict) -> str:
    local = payload["local"]
    dossier = payload["dossier"]
    png = payload["png"]
    sources = payload.get("sources") or {}
    paths = payload.get("paths") or {}
    without = paths.get("without_scout") or {}
    with_ = paths.get("with_scout") or {}
    schema = (paths.get("schema") or {})
    scout_schema = schema.get("scout") or {}
    legacy_schema = schema.get("legacy_mcp") or schema.get("legacy_15") or {}
    phases = local.get("phases_s") or {}
    phase_line = ", ".join(f"{name} {value}s" for name, value in phases.items()) or "(n/a)"
    compare = payload.get("compare_nolm")
    compare_block = ""
    if compare:
        compare_block = (
            "\n## Comparaison --no-llm (second fetch)\n\n"
            f"- Latence : {compare['local']['latency_s']} s\n"
            f"- Dossier visible : {compare['dossier']['visible_chars']} car.\n"
        )
    return (
        f"# Bench scout {ticket}\n"
        f"\n"
        f"Date : {date.today().isoformat()}. CLI locale. Pas une facture Cursor.\n"
        f"\n"
        f"## Avec scout vs sans scout (même fetch Jira)\n"
        f"\n"
        f"| Chemin | Texte dans le chat | PNG | Schémas MCP / tour |\n"
        f"|---|---|---|---|\n"
        f"| Sans scout | {without.get('text_chars', 0)} car. ≈ {without.get('text_tokens_est', 0)} tok "
        f"(Jira {without.get('jira_chars', 0)}) | {without.get('png_count', 0)} fichiers, "
        f"{without.get('png_bytes', 0)} octets **lus** | 0 ici, ou {legacy_schema.get('tool_count', 14)} si ancien MCP "
        f"({legacy_schema.get('chars', 0)} car. ≈ {legacy_schema.get('tokens_est', 0)} tok) |\n"
        f"| Avec scout | {with_.get('visible_chars', 0)} car. ≈ {with_.get('visible_tokens_est', 0)} tok "
        f"| {png.get('count', 0)} fichiers, {png.get('bytes', 0)} octets **disque** | "
        f"2 outils ({scout_schema.get('chars', 0)} car. ≈ {scout_schema.get('tokens_est', 0)} tok) |\n"
        f"\n"
        f"Ratio texte sans/avec : {paths.get('text_ratio', 0)}×. "
        f"Ratio schémas ancien/scout : {schema.get('schema_ratio', 0)}×. "
        f"Les PNG sans scout ne sont pas convertis en chars/4.\n"
        f"\n"
        f"## Compteurs (ne pas les mélanger)\n"
        f"\n"
        f"| Couche | Quoi | Chiffre | Facturé Cursor |\n"
        f"|---|---|---|---|\n"
        f"| Local 9B | Synthèse du dossier | {local['mlx_prompt_tokens']} in / {local['mlx_completion_tokens']} out | non |\n"
        f"| Dossier | Texte unique destiné au chat | {dossier['visible_chars']} car. ≈ {dossier['visible_tokens_est']} tok | oui, si un scout MCP |\n"
        f"| Dossier déterministe | Même run, avant synthèse | {dossier['visible_chars_deterministic']} car. | n/a |\n"
        f"| PNG | {png['count']} captures | {png['bytes']} octets, restées sur disque | non si scout |\n"
        f"| Sources texte | Jira + Confluence + OCR + rg | {sources.get('text_chars', 0)} car. | non (hors dossier) |\n"
        f"| Cursor cartes | Usage avant / après | vide | pas mesurable depuis cette CLI |\n"
        f"\n"
        f"## Run\n"
        f"\n"
        f"- Tickets : {', '.join(payload['tickets']) or '(aucun)'}\n"
        f"- Latence : {local['latency_s']} s ({phase_line})\n"
        f"- mlx_used : {str(local['mlx_used']).lower()}\n"
        f"- Erreurs : {len(payload['errors'])}\n"
        f"- Dossier : {payload['path']}\n"
        f"{compare_block}"
        f"\n"
        f"## Ce que ça ne prouve pas\n"
        f"\n"
        f"Pas de cartes Usage Cursor. Un ratio de caractères n'est pas un delta de facture.\n"
        f"Le 2,2 M du v3 est un chat d'analyse complet, pas cette phase terrain.\n"
    )


def run_bench(
    config: Config,
    ticket: str,
    *,
    mission: str = "",
    out: str | None = None,
    no_llm: bool = False,
    compare_nolm: bool = False,
    client: MlxClient | None = None,
) -> dict:
    out_dir = Path(out).expanduser() if out else (config.repo_root / "temp" / "scout" / "bench")
    if not out_dir.is_absolute():
        out_dir = config.repo_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    text = (mission or "").strip() or f"Déblayer {ticket} pour un diagnostic. Ne pas trancher."
    result = run_scout(
        config,
        text,
        ticket=ticket,
        out=str(out_dir / "run"),
        no_llm=no_llm,
        client=client,
    )
    payload = result_payload(result)
    payload["ticket"] = ticket
    payload["mission"] = text
    if compare_nolm and not no_llm:
        other = run_scout(
            config,
            text,
            ticket=ticket,
            out=str(out_dir / "run-nolm"),
            no_llm=True,
        )
        payload["compare_nolm"] = result_payload(other)
    (out_dir / "bench.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "bench.md").write_text(render_markdown(ticket, payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    config = get_config()
    try:
        payload = run_bench(
            config,
            arguments.ticket.strip(),
            mission=arguments.mission,
            out=arguments.out,
            no_llm=arguments.no_llm,
            compare_nolm=arguments.compare_nolm,
            client=MlxClient(config),
        )
    except (GuardrailError, MlxError, ValueError) as error:
        print(f"local-scout bench : {error}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    out_dir = Path(arguments.out).expanduser()
    if not out_dir.is_absolute():
        out_dir = config.repo_root / out_dir
    print(f"\n# écrit {out_dir / 'bench.md'}", file=sys.stderr)
    return 1 if payload.get("errors") and not payload.get("tickets") else 0
