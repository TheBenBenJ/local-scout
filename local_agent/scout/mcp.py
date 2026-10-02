"""MCP scout : deux outils. L'orchestrateur n'enchaîne plus Jira / OCR / expand."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from ..config import get_config
from ..files import GuardrailError
from ..mlx import MlxError
from ..version import SERVER_VERSION, git_head
from .engine import run_scout

SERVER_NAME = "local-scout"
DEFAULT_PROTOCOL = "2024-11-05"
SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}

TOOLS = [
    {
        "name": "scout_ping",
        "description": "Liveness. No LLM.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "scout",
        "description": (
            "Gather Jira, Confluence, OCR, PDF annots, CI/log failures and rg locally. "
            "Returns one bounded dossier. Pass paths only; sources is a closed list. "
            "If the mission asks to search/JQL/doublon/ticket existant, run JQL even when sources is set. "
            "Un appel par mission. Diagnostiquer depuis le dossier. "
            "Relire seulement les paths marqués tronqués ou re-read_allowed. "
            "Ne pas relire le brut déjà intégral. "
            "PDF: parse Annot (Highlight /Contents), never OCR a PDF as a screenshot. "
            "Log/CI: keep failure lines + context, never the whole trace. "
            "git://: candidate branches + merge status, not which one is right. "
            "use_llm=true also allows one vision pass per weak-OCR screenshot (layout only, "
            "OCR numbers stay authoritative). "
            "Known-symbol grep: orchestrator greps, not scout. PHPStan / short check: not scout."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mission": {
                    "type": "string",
                    "description": "What the diagnosis must decide, plus the ticket key if any.",
                },
                "ticket": {"type": "string", "description": "LYSI-XXXX if already known"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional jira://, confluence://, repo paths, log://<path>, "
                        "ci://gitlab/<project>/<job_id>, git://<pattern-or-ticket>"
                    ),
                },
                "use_llm": {
                    "type": "boolean",
                    "description": "true = add a local 9B synthesis. Default false.",
                },
                "repo": {"type": "string"},
            },
            "required": ["mission"],
        },
    },
]


def want_llm(arguments: dict) -> bool:
    if "use_llm" in arguments:
        return bool(arguments.get("use_llm"))
    if "no_llm" in arguments:
        return not bool(arguments.get("no_llm"))
    return False


def format_ping() -> str:
    head = (git_head() or "")[:7]
    return f"ok\nversion: {SERVER_VERSION}\ngit: {head}\n"


def format_scout(result) -> str:
    ready = bool(getattr(result, "ready", not result.errors))
    lines = [f"ready_for_diagnosis: {str(ready).lower()}"]
    allowed = list(getattr(result, "re_read_allowed", None) or [])
    if allowed:
        lines.append("re-read_allowed:")
        for item in allowed:
            lines.append(f"- {item.get('path')}: {item.get('reason')}")
    markdown = result.markdown or ""
    listed = "## Trous" in markdown or "## Erreurs" in markdown or "## Manqué" in markdown
    if not ready and result.errors and not listed:
        lines.append("errors:")
        lines.extend(f"- {error}" for error in result.errors)
    lines.append("---")
    return "\n".join(lines) + "\n" + markdown


def _config(arguments: dict):
    config = get_config()
    override = str(arguments.get("repo") or "").strip()
    if override and "${" not in override:
        from dataclasses import replace

        config = replace(config, repo_root=Path(override).expanduser().resolve())
    return config


def _handle(name: str, arguments: dict) -> str:
    if name == "scout_ping":
        return format_ping()
    if name != "scout":
        raise ValueError(f"unknown tool: {name}")
    mission = str(arguments.get("mission") or "").strip()
    if not mission:
        raise ValueError("mission is required")
    result = run_scout(
        _config(arguments),
        mission,
        ticket=str(arguments.get("ticket") or "").strip() or None,
        sources=list(arguments.get("sources") or []),
        no_llm=not want_llm(arguments),
    )
    return format_scout(result)


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
