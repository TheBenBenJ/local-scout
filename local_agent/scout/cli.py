"""CLI unique : scout, puis les commandes locales (doctor, task, …)."""

from __future__ import annotations

import argparse
import sys

from ..config import get_config
from ..files import GuardrailError
from ..mlx import MlxClient, MlxError
from .engine import run_scout

TOOL_COMMANDS = {
    "apply",
    "benchmark",
    "check",
    "config",
    "diff",
    "doctor",
    "duplicates",
    "eval",
    "expand",
    "fix",
    "image",
    "image-compare",
    "image-crop",
    "inspect",
    "logs",
    "ping",
    "review",
    "search",
    "session",
    "stats",
    "summarize",
    "task",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-scout",
        description=(
            "Déblaie ticket, captures, doc et code en local. "
            "Sous-commandes : bench, doctor, ping, task, expand, image, …"
        ),
        epilog="Exemples : local-scout --ticket LYSI-6476 · local-scout doctor · local-scout task \"…\" --source log://…",
    )
    parser.add_argument("mission", nargs="?", default="", help="ce que l'orchestrateur devra trancher")
    parser.add_argument("--ticket", default=None, help="LYSI-XXXX")
    parser.add_argument("--source", action="append", dest="sources", help="jira://, confluence://, chemin")
    parser.add_argument("--out", default=None, help="dossier de sortie (défaut temp/scout/<clé>)")
    parser.add_argument("--no-llm", action="store_true", help="extract déterministe seulement")
    parser.add_argument("--json", action="store_true", help="métadonnées JSON, le markdown est quand même écrit")
    return parser


def _result_dict(result) -> dict:
    return {
        "path": str(result.dossier_path),
        "tickets": result.tickets,
        "raw_chars": result.raw_chars,
        "visible_chars": result.visible_chars,
        "visible_chars_deterministic": result.visible_chars_deterministic,
        "mlx_used": result.mlx_used,
        "mlx_prompt_tokens": result.mlx_prompt_tokens,
        "mlx_completion_tokens": result.mlx_completion_tokens,
        "latency_s": result.latency_s,
        "image_count": result.image_count,
        "ledger": result.ledger,
        "errors": result.errors,
    }


def _head_command(argv: list[str]) -> str | None:
    rest = argv[1:] if argv and argv[0] == "--json" else argv
    if rest and not rest[0].startswith("-"):
        return rest[0]
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = _head_command(argv)
    if command == "bench":
        from .bench import main as bench_main

        rest = argv[1:] if argv[0] == "bench" else argv[2:]
        return bench_main(rest)
    if command in TOOL_COMMANDS:
        from ..cli import run

        return run(argv)
    arguments = build_parser().parse_args(argv)
    mission = (arguments.mission or "").strip()
    ticket = (arguments.ticket or "").strip() or None
    if not mission and ticket:
        mission = f"Déblayer {ticket} pour un diagnostic."
    if not mission:
        print("local-scout : mission, --ticket, ou une sous-commande (doctor, bench, task, …)", file=sys.stderr)
        return 2
    config = get_config()
    try:
        result = run_scout(
            config,
            mission,
            ticket=ticket,
            sources=arguments.sources,
            out=arguments.out,
            no_llm=arguments.no_llm,
            client=MlxClient(config),
        )
    except (GuardrailError, MlxError, ValueError) as error:
        print(f"local-scout : {error}", file=sys.stderr)
        return 1
    if arguments.json:
        import json

        print(json.dumps(_result_dict(result), ensure_ascii=False, indent=2))
        return 0
    print(result.markdown, end="")
    print(f"\n# écrit {result.dossier_path}", file=sys.stderr)
    return 1 if result.errors and not result.tickets else 0
