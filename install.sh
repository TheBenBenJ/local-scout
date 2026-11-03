#!/usr/bin/env bash
# Register the scout MCP server (2 tools) for Cursor / Claude Code.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for tool in python3 rg git; do
    if ! command -v "$tool" > /dev/null 2>&1; then
        echo "missing prerequisite: $tool" >&2
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
            print(f"{label}: {path} is unreadable, left unchanged.")
            return
    servers = payload.setdefault("mcpServers", {})
    env = {}
    for name in ("local-scout", "local-agent"):
        current = servers.get(name)
        if isinstance(current, dict) and current.get("env"):
            env = current["env"]
            break
    if "local-agent" in servers:
        print(f"{label}: local-agent removed (15 tool schemas on every turn).")
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
    print(f"{label}: scout registered in {path}.")


register(Path.home() / ".claude.json", "Claude Code")
register(Path.home() / ".cursor" / "mcp.json", "Cursor")
PY

echo
python3 "$ROOT/bin/local-scout" doctor || true
echo
echo "Done. Restart Cursor / Claude Code, then call scout_ping."
echo "CLI: $ROOT/bin/local-scout --ticket PROJ-123"
echo "     $ROOT/bin/local-scout doctor"
