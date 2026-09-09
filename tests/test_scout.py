#!/usr/bin/env python3
"""Scout : extract, dossier borné, ledger, MCP 2 outils. Pas de Jira live."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_agent.scout import extract  # noqa: E402
from local_agent.scout.dossier import Dossier, write_dossier  # noqa: E402
from local_agent.scout.mcp import TOOLS, Server  # noqa: E402
from local_agent.scout.stats import SourceLedger  # noqa: E402


def check(name: str, condition: bool) -> None:
    status = "OK" if condition else "KO"
    print(f"  {status}  {name}")
    if not condition:
        raise SystemExit(1)


def main() -> None:
    text = (
        "Analyse LYSI-6476 et LYSI-1384. Page confluence://1512833051 "
        "et src/Services/Paie/PaieService.php getDureesMensuelles. "
        "Salarié 019fcb8a-f05a-765d-9c4b-b3a8b892c97b. "
        "image-20260904-095346.png"
    )
    keys = extract.ticket_keys(text, primary="LYSI-6476")
    check("clé primaire en tête", keys[0] == "LYSI-6476")
    check("ticket lié", "LYSI-1384" in keys)
    check("page confluence", extract.confluence_ids(text) == ["1512833051"])
    check(
        "url confluence atlassian",
        extract.confluence_ids(
            "https://6tmgroup.atlassian.net/wiki/spaces/LYSI/pages/1512833051/Mensu"
        )
        == ["1512833051"],
    )
    check("fichier repo", "src/Services/Paie/PaieService.php" in extract.repo_files(text))
    check("uuid", "019fcb8a-f05a-765d-9c4b-b3a8b892c97b" in extract.uuids(text))
    check("image jira", "image-20260904-095346.png" in extract.image_names(text))
    check("symbole", "getDureesMensuelles" in extract.symbols(text))
    check("slug ticket", extract.slug("x", "LYSI-6476") == "LYSI-6476")

    prose = "Exemple Commentaire createSalariePointage dans PaieService et getDureesMensuelles"
    found = extract.symbols(prose)
    check("exemple filtré", "Exemple" not in found and "Commentaire" not in found)
    check("méthodes avant classes", found[0][0].islower())
    check(
        "mission avant ticket",
        extract.merge(["createSalariePointage"], ["Exemple", "getDureesMensuelles"], limit=4)[0]
        == "createSalariePointage",
    )

    ledger = SourceLedger()
    ledger.add_text("jira", "a" * 100)
    ledger.add_text("ocr", "b" * 40)
    dossier = Dossier(mission="x" * 50, holes=["aucun"], ledger=ledger, raw_chars=140)
    dossier.tickets.append(
        {
            "key": "LYSI-1",
            "goal": "titre",
            "issuetype": "Anomalie",
            "status": "En cours",
            "acceptance_criteria_verbatim": "corps " * 4000,
            "comments": [],
        }
    )
    rendered = dossier.markdown(cap=800)
    check("plafond dossier", len(rendered) <= 800 + 5)
    check("mention tronqué", "tronqué" in rendered)
    check("markdown ne touche pas le ledger", dossier.ledger.jira_chars == 100)
    check("markdown ne touche pas raw_chars", dossier.raw_chars == 140)
    check("to_json raw = ledger texte", dossier.to_json()["raw_chars"] == 140)

    packed = Dossier(mission="m", synthesis="synthèse courte")
    packed.tickets.append(
        {
            "key": "LYSI-1",
            "goal": "titre",
            "issuetype": "Anomalie",
            "status": "Ouvert",
            "acceptance_criteria_verbatim": "corps ticket " * 200,
            "comments": [{"author": "A", "created": "2026-01-01", "body": "commentaire " * 80}],
        }
    )
    packed.images = [{"name": f"image-{index}.png", "transcript": "OCR " * 400} for index in range(4)]
    packed_md = packed.markdown()
    check("captures avant tickets", packed_md.index("## Captures") < packed_md.index("## Tickets"))
    check("quatre images dans le plafond", all(f"image-{index}.png" in packed_md for index in range(4)))

    with tempfile.TemporaryDirectory() as tmp:
        written, json_path = write_dossier(Dossier(mission="hello", ledger=ledger), Path(tmp))
        body = written.read_text(encoding="utf-8")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        check("écriture md", written.is_file() and "prêt pour le diagnostic" in body)
        check("json visible = md", payload["visible_chars"] == len(body))
        check("json raw = ledger", payload["raw_chars"] == 140)
        check("json ledger jira", payload["ledger"]["jira_chars"] == 100)

    from local_agent.scout.cli import TOOL_COMMANDS, _head_command

    check("doctor sous-commande", "doctor" in TOOL_COMMANDS and "task" in TOOL_COMMANDS)
    check("head doctor", _head_command(["doctor"]) == "doctor")
    check("head --json doctor", _head_command(["--json", "doctor"]) == "doctor")
    check("head scout pas commande", _head_command(["--ticket", "LYSI-1"]) is None)

    names = {item["name"] for item in TOOLS}
    check("deux outils", names == {"scout", "scout_ping"})
    server = Server()
    listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    check("tools/list", len(listed["result"]["tools"]) == 2)
    ping = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
    )
    check("serverInfo scout", ping["result"]["serverInfo"]["name"] == "local-scout")

    from local_agent.scout.compare import compare_paths, schema_tax
    from local_agent.scout.engine import ScoutResult

    schemas = schema_tax()
    check("schémas scout < 15 outils", schemas["scout"]["chars"] < schemas["legacy_mcp"]["chars"])
    check("deux outils scout", schemas["scout"]["tool_count"] == 2)
    check("quatorze outils legacy", schemas["legacy_mcp"]["tool_count"] == 14)
    fake = ScoutResult(
        out_dir=Path("/tmp"),
        dossier_path=Path("/tmp/dossier.md"),
        markdown="x" * 1000,
        raw_chars=8000,
        visible_chars=1000,
        visible_chars_deterministic=900,
        mlx_used=False,
        mlx_prompt_tokens=0,
        mlx_completion_tokens=0,
        latency_s=0.0,
        tickets=["LYSI-1"],
        errors=[],
        image_count=4,
        ledger={"jira_chars": 6000, "confluence_chars": 0, "code_chars": 0, "ocr_chars": 7000, "image_bytes": 400000},
    )
    paths = compare_paths(fake)
    check("sans scout = jira pas ocr", paths["without_scout"]["text_chars"] == 6000)
    check("avec scout = visible", paths["with_scout"]["visible_chars"] == 1000)
    check("png hors prompt avec scout", paths["with_scout"]["png_in_prompt"] is False)
    print("test_scout OK")


if __name__ == "__main__":
    main()
