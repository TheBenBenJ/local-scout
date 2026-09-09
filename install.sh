#!/usr/bin/env bash
# Enregistre le MCP scout (2 outils) pour Cursor / Claude Code.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for tool in python3 rg git; do
    if ! command -v "$tool" > /dev/null 2>&1; then
        echo "prérequis manquant : $tool" >&2
        exit 1
    fi
done

chmod +x "$ROOT/bin/local-scout" "$ROOT/bin/local-scout-mcp"

python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])


def register(path: Path, label: str) -> None:
    payload = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"{label} : {path} illisible, non modifié.")
            return
    servers = payload.setdefault("mcpServers", {})
    env = {}
    for name in ("local-scout", "local-agent"):
        current = servers.get(name)
        if isinstance(current, dict) and current.get("env"):
            env = current["env"]
            break
    if "local-agent" in servers:
        print(f"{label} : local-agent retiré (15 schémas d'outils à chaque tour).")
        servers.pop("local-agent", None)
    entry = {
        "command": "python3",
        "args": [str(root / "bin" / "local-scout-mcp")],
    }
    if env:
        entry["env"] = env
    servers["local-scout"] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{label} : scout dans {path}.")


register(Path.home() / ".claude.json", "Claude Code")
register(Path.home() / ".cursor" / "mcp.json", "Cursor")
PY

echo
python3 "$ROOT/bin/local-scout" doctor || true
echo
echo "Terminé. Redémarrer Cursor / Claude Code, puis scout_ping."
echo "CLI : $ROOT/bin/local-scout --ticket LYSI-XXXX"
echo "      $ROOT/bin/local-scout doctor"
