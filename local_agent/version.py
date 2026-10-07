"""Install identity shown by ping and doctor. Not a billed-usage meter."""

from __future__ import annotations

import subprocess
from pathlib import Path

SERVER_NAME = "local-scout"
SERVER_VERSION = "1.10.4"
ROOT = Path(__file__).resolve().parent.parent


def git_head() -> str:
    try:
        got = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if got.returncode == 0:
        return (got.stdout or "").strip()
    try:
        head = (ROOT / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if head.startswith("ref:"):
        try:
            return (ROOT / ".git" / head.split(" ", 1)[1].strip()).read_text(encoding="utf-8").strip()[:12]
        except OSError:
            return ""
    return head[:12]


def disk_version() -> str:
    """Version du code sur disque : un serveur MCP long garde en mémoire celle de son démarrage."""
    try:
        text = (ROOT / "local_agent" / "version.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        if line.startswith("SERVER_VERSION"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def stale_note() -> str:
    on_disk = disk_version()
    if on_disk and on_disk != SERVER_VERSION:
        return (
            f"serveur scout périmé : {SERVER_VERSION} en mémoire, {on_disk} sur disque. "
            "Redémarrer la session (ou le client MCP) pour charger le code à jour."
        )
    return ""


def describe() -> dict[str, str]:
    return {
        "name": SERVER_NAME,
        "version": SERVER_VERSION,
        "git_head": git_head(),
        "code_root": str(ROOT),
    }
