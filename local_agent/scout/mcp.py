"""MCP scout : deux outils. L'orchestrateur n'enchaîne plus Jira / OCR / expand."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from ..config import get_config
from ..files import GuardrailError
from ..mlx import MlxClient, MlxError
from ..ocr import backend_status
from ..version import SERVER_VERSION, git_head
from .engine import run_scout

SERVER_NAME = "local-scout"
DEFAULT_PROTOCOL = "2024-11-05"
SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}

TOOLS = [
    {
        "name": "scout_ping",
        "description": "Vérifie que le scout et le dépôt sont utilisables. N'appelle pas le LLM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Racine git si ce n'est pas LOCAL_AGENT_REPO_ROOT.",
                }
            },
        },
    },
    {
        "name": "scout",
        "description": (
            "Déblaie le terrain en local (Jira, Confluence, OCR, rg) puis rend UN dossier borné. "
            "Premier et presque seul appel d'un chat d'analyse. "
            "Ne pas enchaîner avec local_task / local_expand / Read des sources listées. "
            "Le diagnostic se fait ensuite à partir du dossier uniquement."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mission": {
                    "type": "string",
                    "description": "Ce que le diagnostic devra trancher, plus la clé ticket s'il y en a une.",
                },
                "ticket": {"type": "string", "description": "LYSI-XXXX si déjà connue"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Pointeurs optionnels jira://, confluence://, chemins repo",
                },
                "out": {"type": "string", "description": "Dossier de sortie relatif au dépôt"},
                "no_llm": {
                    "type": "boolean",
                    "description": "true = extract déterministe seulement, sans synthèse 9B",
                },
                "repo": {"type": "string"},
            },
            "required": ["mission"],
        },
    },
]


def _config(arguments: dict):
    config = get_config()
    override = str(arguments.get("repo") or "").strip()
    if override and "${" not in override:
        from dataclasses import replace

        config = replace(config, repo_root=Path(override).expanduser().resolve())
    return config


def _handle(name: str, arguments: dict) -> str:
    config = _config(arguments)
    if name == "scout_ping":
        mlx_ok = False
        mlx_error = ""
        try:
            MlxClient(config).models()
            mlx_ok = True
        except MlxError as error:
            mlx_error = str(error)
        payload = {
            "alive": True,
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "git_head": git_head(),
            "repo_root": str(config.repo_root),
            "ocr": (backend_status() or {}).get("preferred"),
            "mlx_reachable": mlx_ok,
            "mlx_error": mlx_error or None,
            "usage": "Call scout once with the ticket/mission. Do not orchestrate local-agent tools.",
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if name != "scout":
        raise ValueError(f"unknown tool: {name}")
    mission = str(arguments.get("mission") or "").strip()
    if not mission:
        raise ValueError("mission is required")
    result = run_scout(
        config,
        mission,
        ticket=str(arguments.get("ticket") or "").strip() or None,
        sources=list(arguments.get("sources") or []),
        out=str(arguments.get("out") or "").strip() or None,
        no_llm=bool(arguments.get("no_llm")),
    )
    ledger = result.ledger or {}
    header = (
        f"ready_for_diagnosis: true\n"
        f"path: {result.dossier_path}\n"
        f"tickets: {', '.join(result.tickets) or '(aucun)'}\n"
        f"visible_chars: {result.visible_chars}\n"
        f"source_text_chars: {result.raw_chars}\n"
        f"jira_chars: {ledger.get('jira_chars', 0)}\n"
        f"ocr_chars: {ledger.get('ocr_chars', 0)}\n"
        f"image_bytes: {ledger.get('image_bytes', 0)}\n"
        f"mlx_used: {str(result.mlx_used).lower()}\n"
        f"mlx_prompt_tokens: {result.mlx_prompt_tokens}\n"
        f"mlx_completion_tokens: {result.mlx_completion_tokens}\n"
        f"errors: {len(result.errors)}\n"
        "---\n"
    )
    return header + result.markdown


class Server:
    def __init__(self) -> None:
        self.protocol = DEFAULT_PROTOCOL

    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        identifier = message.get("id")
        params = message.get("params") or {}
        if method == "initialize":
            requested = str(params.get("protocolVersion") or "")
            self.protocol = requested if requested in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
            return self._result(
                identifier,
                {
                    "protocolVersion": self.protocol,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return self._result(identifier, {})
        if method == "tools/list":
            return self._result(identifier, {"tools": TOOLS})
        if method in ("resources/list", "resources/templates/list"):
            return self._result(identifier, {"resources": [], "resourceTemplates": []})
        if method == "prompts/list":
            return self._result(identifier, {"prompts": []})
        if method == "tools/call":
            return self._call(identifier, params)
        if identifier is None:
            return None
        return self._error(identifier, -32601, f"unsupported method: {method}")

    def _call(self, identifier, params: dict) -> dict:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        try:
            text = _handle(name, arguments)
            return self._result(identifier, {"content": [{"type": "text", "text": text}], "isError": False})
        except (GuardrailError, MlxError, ValueError) as error:
            message = f"local-scout ({name}) refused or failed: {error}"
        except Exception as error:  # noqa: BLE001
            print(traceback.format_exc(), file=sys.stderr)
            message = f"local-scout ({name}) internal error: {type(error).__name__} {error}"
        return self._result(
            identifier,
            {"content": [{"type": "text", "text": message}], "isError": True},
        )

    @staticmethod
    def _result(identifier, payload: dict) -> dict:
        return {"jsonrpc": "2.0", "id": identifier, "result": payload}

    @staticmethod
    def _error(identifier, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


def serve() -> None:
    server = Server()
    stream = sys.stdin
    while True:
        line = stream.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print("local-scout MCP: ignored invalid JSON line", file=sys.stderr)
            continue
        response = server.handle(message)
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    try:
        serve()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
