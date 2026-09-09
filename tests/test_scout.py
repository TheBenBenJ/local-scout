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
from local_agent.scout.mcp import TOOLS, Server, _handle, want_llm, format_ping  # noqa: E402
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
    check("plafond dossier", len(rendered) <= 800)
    check("mention truncated", "[truncated]" in rendered or "omitted" in rendered)
    check("trous sous petit plafond", "## Trous" in rendered)
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
        check("écriture md", written.is_file() and "Dossier scout" in body)
        check("json visible = md", payload["visible_chars"] == len(body))
        check("json raw = ledger", payload["raw_chars"] == 140)
        check("json ledger jira", payload["ledger"]["jira_chars"] == 100)

    from local_agent.scout.cli import TOOL_COMMANDS, _head_command

    check("doctor sous-commande", "doctor" in TOOL_COMMANDS and "task" in TOOL_COMMANDS)
    check("head doctor", _head_command(["doctor"]) == "doctor")
    check("head --json doctor", _head_command(["--json", "doctor"]) == "doctor")
    check("head scout pas commande", _head_command(["--ticket", "LYSI-1"]) is None)

    ROOT_CAUSE = "InvoiceService::computeTotal returns null when line.qty is 0"
    fat = Dossier(
        mission="Why is the invoice total empty?",
        holes=["HOLE-missing-stacktrace-worker-7"],
        errors=["LYSI-9: timeout"],
    )
    fat.images = [
        {"name": f"cap-{index}.png", "transcript": f"CAPTURE-PROOF-{index} " + ("ocr " * 400)}
        for index in range(8)
    ]
    fat.tickets = [
        {
            "key": "LYSI-9",
            "goal": "total vide",
            "issuetype": "Anomalie",
            "status": "Ouvert",
            "acceptance_criteria_verbatim": "TICKET-PROOF-LYSI-9 " + ("body " * 800),
            "comments": [],
        },
        {
            "key": "LYSI-10",
            "goal": "suite",
            "issuetype": "Anomalie",
            "status": "Ouvert",
            "acceptance_criteria_verbatim": "TICKET-PROOF-LYSI-10 " + ("body " * 800),
            "comments": [],
        },
    ]
    fat.pages = [
        {"title": "Page A", "body": "CONFLUENCE-PROOF-A " + ("page " * 600)},
        {"title": "Page B", "body": "CONFLUENCE-PROOF-B " + ("page " * 600)},
        {"title": "Page C", "body": "CONFLUENCE-PROOF-C " + ("page " * 600)},
    ]
    fat.code = [
        {
            "location": "src/InvoiceService.php:88",
            "file": "src/InvoiceService.php",
            "text": ROOT_CAUSE + "\n" + ("x" * 200),
        }
    ]
    unbounded = fat.markdown(cap=200_000)
    legacy = unbounded[:12_000]
    packed = fat.markdown()
    check("slicing global perd le code", ROOT_CAUSE not in legacy)
    check("slicing global perd les trous", "HOLE-missing-stacktrace-worker-7" not in legacy)
    check("budget respecté", len(packed) <= 12_000)
    check("root cause conservée", ROOT_CAUSE in packed)
    check("preuve ticket", "TICKET-PROOF-LYSI-9" in packed)
    check("preuve confluence", "CONFLUENCE-PROOF-A" in packed)
    check("preuve capture", "CAPTURE-PROOF-0" in packed)
    check("holes conservés", "HOLE-missing-stacktrace-worker-7" in packed)
    check("errors conservées", "LYSI-9: timeout" in packed)
    check("instructions conservées", "## À l'orchestrateur" in packed)

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

    check("want_llm default", want_llm({}) is False)
    check("want_llm use_llm", want_llm({"use_llm": True}) is True)
    check("want_llm no_llm false", want_llm({"no_llm": False}) is True)
    check("want_llm no_llm true", want_llm({"no_llm": True}) is False)

    ping_text = format_ping()
    check("ping compact", ping_text.startswith("ok\n") and "version:" in ping_text and "git:" in ping_text)
    check("ping sans config", "repo_root" not in ping_text and "mlx" not in ping_text.lower())
    check("ping via handle", _handle("scout_ping", {}) == ping_text)

    scout_props = next(item["inputSchema"]["properties"] for item in TOOLS if item["name"] == "scout")
    check("out absent du schéma", "out" not in scout_props)
    check("use_llm dans le schéma", "use_llm" in scout_props)

    import local_agent.scout.engine as engine_mod
    from local_agent.mlx import Completion

    tmp = Path(tempfile.mkdtemp())
    (tmp / "src").mkdir()
    original_mlx = engine_mod.MlxClient

    class BoomClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("MlxClient must not be constructed on the MCP default path")

    engine_mod.MlxClient = BoomClient
    try:
        default_payload = _handle("scout", {"mission": "Inventaire local sans ticket.", "repo": str(tmp)})
    finally:
        engine_mod.MlxClient = original_mlx
    envelope = default_payload.split("---", 1)[0]
    check("MCP défaut sans crash LLM", "ready_for_diagnosis:" in envelope)
    check("MCP envelope sans path", "path:" not in envelope)
    check("MCP envelope sans visible_chars", "visible_chars" not in envelope)
    check("MCP envelope sans jira_chars", "jira_chars" not in envelope)
    check("MCP envelope sans mlx_used", "mlx_used" not in envelope)
    check("MCP envelope sans tickets:", "tickets:" not in envelope)

    evil = Path(tempfile.mkdtemp()) / "must-not-exist"
    engine_mod.MlxClient = BoomClient
    try:
        _handle(
            "scout",
            {
                "mission": "Inventaire local sans ticket.",
                "repo": str(tmp),
                "out": str(evil),
            },
        )
    finally:
        engine_mod.MlxClient = original_mlx
    check("out MCP ignoré", not evil.exists())
    check("écriture sous le repo", any(tmp.glob("temp/scout/*/dossier.md")))

    class FakeClient:
        complete_calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def models(self):
            return ["qwen"]

        def complete(self, prompt, system, **kwargs):
            FakeClient.complete_calls += 1
            return Completion(text="synthèse locale de test", prompt_tokens=3, completion_tokens=5)

    FakeClient.complete_calls = 0
    engine_mod.MlxClient = FakeClient
    try:
        llm_payload = _handle(
            "scout",
            {"mission": "Inventaire local sans ticket.", "repo": str(tmp), "use_llm": True},
        )
    finally:
        engine_mod.MlxClient = original_mlx
    check("MCP use_llm appelle complete", FakeClient.complete_calls == 1)
    check("synthèse MCP", "synthèse locale de test" in llm_payload)

    print("test_scout OK")


if __name__ == "__main__":
    main()
