"""Avec scout vs sans scout, sur les mêmes sources. Pas une facture Cursor."""

from __future__ import annotations

import json

from ..budget import tokens_from_chars
from . import mcp as scout_mcp
from .engine import ScoutResult


def _schema(tools: list) -> dict:
    raw = json.dumps({"tools": tools}, ensure_ascii=False)
    return {
        "tool_count": len(tools),
        "chars": len(raw),
        "tokens_est": tokens_from_chars(len(raw)),
    }


def schema_tax() -> dict:
    from ..mcp import TOOLS as legacy_tools

    scout = _schema(scout_mcp.TOOLS)
    legacy = _schema(legacy_tools)
    return {
        "scout": scout,
        "legacy_mcp": legacy,
        "schema_ratio": round(legacy["chars"] / scout["chars"], 1) if scout["chars"] else 0.0,
    }


def compare_paths(result: ScoutResult) -> dict:
    ledger = result.ledger or {}
    jira = int(ledger.get("jira_chars") or 0)
    confluence = int(ledger.get("confluence_chars") or 0)
    code = int(ledger.get("code_chars") or 0)
    ocr = int(ledger.get("ocr_chars") or 0)
    png_bytes = int(ledger.get("image_bytes") or 0)
    without_text = jira + confluence + code
    with_chars = int(result.visible_chars)
    return {
        "without_scout": {
            "jira_chars": jira,
            "confluence_chars": confluence,
            "code_chars": code,
            "text_chars": without_text,
            "text_tokens_est": tokens_from_chars(without_text),
            "png_bytes": png_bytes,
            "png_count": result.image_count,
            "png_in_prompt": True,
            "note": (
                "Jira + Confluence + rg, plus Read des PNG. "
                "Pas d'OCR local : les captures entrent en Vision. "
                "Les octets PNG ne sont pas des tokens chars/4."
            ),
        },
        "with_scout": {
            "visible_chars": with_chars,
            "visible_tokens_est": tokens_from_chars(with_chars),
            "ocr_chars_in_dossier": ocr,
            "png_bytes_on_disk": png_bytes,
            "png_in_prompt": False,
            "mlx_prompt_tokens": result.mlx_prompt_tokens,
            "mlx_completion_tokens": result.mlx_completion_tokens,
            "note": "Un dossier borné. PNG hors chat. 9B facturé en local.",
        },
        "text_ratio": round(without_text / with_chars, 2) if with_chars else 0.0,
        "schema": schema_tax(),
    }
