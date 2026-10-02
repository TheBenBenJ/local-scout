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
from .cases import (
    CASES,
    DEFAULT_CASE_IDS,
    get_case,
    render_score,
    resolve_sources,
    score_markdown,
    score_to_dict,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-scout bench",
        description="Mesure locale du scout. N'invente pas de cartes Cursor.",
    )
    parser.add_argument("--ticket", default="", help="LYSI-XXXX (run libre, sans grille)")
    parser.add_argument("--mission", default="", help="mission passée au scout")
    parser.add_argument("--out", default="temp/scout/bench", help="dossier de sortie")
    parser.add_argument("--no-llm", action="store_true", help="sans synthèse 9B")
    parser.add_argument("--repo", default="", help="dépôt client (sinon LOCAL_AGENT_REPO_ROOT / cwd)")
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="cas terrain (LYSI-6160, LYSI-6417-pdf, LYSI-6417-dir, LYSI-6553-c1, LYSI-6553-c2)",
    )
    parser.add_argument("--cases", action="store_true", dest="all_cases", help="tous les cas terrain")
    parser.add_argument("--print-prompt", metavar="CASE", help="afficher le prompt de conversation")
    parser.add_argument("--score-dossier", metavar="FILE", help="noter un dossier.md déjà produit")
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


def _config_with_repo(repo: str):
    config = get_config()
    override = (repo or "").strip()
    if override and "${" not in override:
        from dataclasses import replace

        config = replace(config, repo_root=Path(override).expanduser().resolve())
    return config


def run_case(config: Config, case_id: str, *, out_dir: Path, no_llm: bool = True, client=None) -> dict:
    case = get_case(case_id)
    sources, missing = resolve_sources(config.repo_root, case)
    if missing:
        return {
            "case": case.id,
            "skipped": True,
            "reason": missing,
            "score": None,
        }
    result = run_scout(
        config,
        case.mission,
        ticket=case.ticket,
        sources=sources or None,
        out=str(out_dir / case.id),
        no_llm=no_llm,
        client=client,
    )
    envelope = ""
    try:
        from .mcp import format_scout

        envelope = format_scout(result)
    except Exception:  # noqa: BLE001
        envelope = result.markdown
    scored = score_markdown(envelope, case, mode="live", ready=result.ready)
    payload = result_payload(result)
    payload["case"] = case.id
    payload["title"] = case.title
    payload["mission"] = case.mission
    payload["sources"] = sources
    payload["skipped"] = False
    payload["score"] = score_to_dict(scored)
    payload["score_md"] = render_score(scored)
    return payload


def run_case_suite(config: Config, case_ids: list[str], *, out: str, no_llm: bool = True, client=None) -> dict:
    out_dir = Path(out).expanduser() if out else (config.repo_root / "temp" / "scout" / "bench")
    if not out_dir.is_absolute():
        out_dir = config.repo_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for ident in case_ids:
        rows.append(run_case(config, ident, out_dir=out_dir, no_llm=no_llm, client=client))
    scored = [item for item in rows if item.get("score")]
    payload = {
        "date": date.today().isoformat(),
        "repo": str(config.repo_root),
        "cases": rows,
        "summary": {
            "ran": len(scored),
            "skipped": sum(1 for item in rows if item.get("skipped")),
            "ok": sum(1 for item in scored if (item.get("score") or {}).get("ok")),
            "mean_pct": round(
                sum((item.get("score") or {}).get("pct") or 0 for item in scored) / len(scored), 1
            )
            if scored
            else 0.0,
        },
        "cursor": {
            "note": "Cartes Usage : les remplir dans docs/session-prompts.md, pas ici.",
        },
    }
    md_parts = [
        f"# Bench cas terrain\n\nDate : {payload['date']}. Repo : `{payload['repo']}`.\n",
        f"Joués {payload['summary']['ran']}, skip {payload['summary']['skipped']}, "
        f"OK {payload['summary']['ok']}, moyenne {payload['summary']['mean_pct']} %.\n",
    ]
    for item in rows:
        if item.get("skipped"):
            md_parts.append(f"## {item.get('case')} — skip\n\n{item.get('reason')}\n")
            continue
        md_parts.append(item.get("score_md") or "")
        md_parts.append("")
    (out_dir / "cases.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "cases.md").write_text("\n".join(md_parts).rstrip() + "\n", encoding="utf-8")
    payload["path"] = str(out_dir / "cases.md")
    return payload


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.print_prompt:
        case = get_case(arguments.print_prompt)
        print(case.prompt, end="" if case.prompt.endswith("\n") else "\n")
        return 0
    config = _config_with_repo(arguments.repo)
    out_dir = Path(arguments.out).expanduser()
    if not out_dir.is_absolute():
        out_dir = config.repo_root / out_dir

    if arguments.score_dossier:
        if not arguments.cases:
            print("local-scout bench : --score-dossier exige --case ID", file=sys.stderr)
            return 2
        case = get_case(arguments.cases[0])
        text = Path(arguments.score_dossier).expanduser().read_text(encoding="utf-8")
        scored = score_markdown(text, case, mode="live")
        print(render_score(scored))
        print(json.dumps(score_to_dict(scored), ensure_ascii=False, indent=2))
        return 0 if scored.ok else 1

    case_ids = list(arguments.cases or [])
    if arguments.all_cases:
        case_ids = list(DEFAULT_CASE_IDS)
    if case_ids:
        try:
            payload = run_case_suite(
                config,
                case_ids,
                out=arguments.out,
                no_llm=True,
                client=MlxClient(config),
            )
        except (GuardrailError, MlxError, ValueError) as error:
            print(f"local-scout bench : {error}", file=sys.stderr)
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\n# écrit {payload.get('path')}", file=sys.stderr)
        failed = [
            item
            for item in payload.get("cases") or []
            if not item.get("skipped") and not (item.get("score") or {}).get("ok")
        ]
        return 1 if failed else 0

    ticket = (arguments.ticket or "").strip()
    if not ticket:
        print(
            "local-scout bench : --ticket LYSI-XXXX, ou --cases, ou --print-prompt ID",
            file=sys.stderr,
        )
        print("cas : " + ", ".join(CASES), file=sys.stderr)
        return 2
    try:
        payload = run_bench(
            config,
            ticket,
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
    print(f"\n# écrit {out_dir / 'bench.md'}", file=sys.stderr)
    return 1 if payload.get("errors") and not payload.get("tickets") else 0
