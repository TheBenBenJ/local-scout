#!/usr/bin/env python3
"""Scout : extract, dossier borné, ledger, MCP 2 outils. Pas de Jira live."""

from __future__ import annotations

import json
import os
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


def score_case(case_id: str, markdown: str, ready: bool | None) -> None:
    from local_agent.scout.cases import get_case, score_markdown

    scored = score_markdown(markdown, get_case(case_id), mode="fixture", ready=ready)
    failed = [f"{item.id} ({item.detail})" for item in scored.hits if not item.ok]
    check(f"{case_id} grille {scored.passed}/{scored.total}", not failed)


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
    bundle = "lib/facture-electronique-bundle/src/Iopole/Connector/IopoleConnector.php"
    check("chemin lib conservé", extract.repo_files(f"voir {bundle}") == [bundle])
    check(
        "source recopié tel quel",
        extract.source_paths([bundle]) == [bundle],
    )
    check("handler utile", "EreportingQuotidienMessageHandler" in extract.symbols(
        "Voir EreportingQuotidienMessageHandler et createAndSubmitLotsOn"
    ))
    check("revue détectée", extract.is_review("Revue de code LYSI-6160") is True)
    check("revue sans OCR", extract.wants_ocr("Revue de code sans UI", "") is False)
    check("uuid", "019fcb8a-f05a-765d-9c4b-b3a8b892c97b" in extract.uuids(text))
    check(
        "jql demandé",
        extract.wants_jira_search(
            "fetch LYSI-6005 et chercher un ticket existant sur le même défaut"
        )
        is True,
    )
    check("revue sans jql", extract.wants_jira_search("Revue de code LYSI-6160 lots SIREN") is False)
    hits = extract.url_uuid_hits(
        "https://x/planification-bons-travaux/0194d54a-f05a-7000-8000-000000000001/"
    )
    check("url uuid slug", hits and hits[0][0] == "planification-bons-travaux")
    check(
        "salarieId n'est pas planif",
        extract.entity_for_route_param("salarieId")[1] == "ce n'est pas l'id de planification",
    )
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
    check("tickets avant captures", packed_md.index("## Ticket") < packed_md.index("## Captures"))
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
    packed = fat.markdown()
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
    scout_desc = next(item["description"] for item in TOOLS if item["name"] == "scout")
    check("contrat relire tronqués", "Relire seulement les paths marqués tronqués" in scout_desc)
    from local_agent.scout.cases import CASES, get_case

    check("cinq cas terrain", set(CASES) >= {"LYSI-6160", "LYSI-6417-pdf", "LYSI-6417-dir", "LYSI-6553-c1", "LYSI-6553-c2"})
    check("prompt 6553-c2 collable", "Recherche Jira" in get_case("LYSI-6553-c2").prompt)
    check("interdit de relire retiré", "Do not re-read listed sources" not in scout_desc)
    check("chemins seulement", "Pass paths only" in scout_desc)
    check("grep symbole hors scout", "Known-symbol grep" in scout_desc)
    check("sources fermées", "closed list" in scout_desc)
    check("JQL malgré sources", "JQL even when sources" in scout_desc)
    check("PDF annots dans le contrat", "Annot" in scout_desc)
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

    _test_lys_6160()
    _test_lys_6417()
    _test_lys_6553()
    _test_logs_extract()
    _test_ticket_truncation_flagged()
    _test_extraction_mission()
    _test_maybe_vision()
    _test_gitarch()
    _test_gather_log_source()
    _test_gather_git_source()
    _test_gitlab_provider()

    print("test_scout OK")


def _write(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _test_lys_6160() -> None:
    from local_agent.config import Config
    from local_agent.scout import gather as gather_mod
    from local_agent.scout.engine import run_scout

    repo = Path(tempfile.mkdtemp())
    connector = "lib/facture-electronique-bundle/src/Iopole/Connector/IopoleConnector.php"
    handler = (
        "lib/facture-electronique-bundle/src/MessageHandler/"
        "EreportingQuotidienMessageHandler.php"
    )
    repository = "lib/facture-electronique-bundle/src/Repository/FactureRepository.php"
    _write(
        repo,
        connector,
        "<?php\nnamespace Iopole\\Connector;\nclass IopoleConnector {\n"
        "    public const PAYMENT_DATE = 'paymentDate';\n"
        "    public function resolveReport(): void {}\n"
        "    public function applyStatut(): void {}\n}\n",
    )
    _write(
        repo,
        handler,
        "<?php\nnamespace Iopole\\MessageHandler;\n"
        "class EreportingQuotidienMessageHandler {\n"
        "    public function __construct(private FactureRepository $repository) {}\n"
        "    public function __invoke($message): void {\n"
        "        $this->createAndSubmitLotsOn($message->getDate());\n"
        "    }\n"
        "    public function createAndSubmitLotsOn(\\DateTimeInterface $day): void {\n"
        "        $factures = $this->repository->findValideesParticulierSansLotOn($day);\n"
        "        foreach ($factures as $lot) {\n"
        "            if ($this->repository->findLotSirenJour($lot->getSiren(), $day)) {\n"
        "                continue;\n"
        "            }\n"
        "            $this->submit($lot);\n"
        "            $this->entityManager->flush();\n"
        "        }\n"
        "    }\n}\n",
    )
    dummy = "\n".join(f"    public function padding{index}(): void {{}}" for index in range(80))
    _write(
        repo,
        repository,
        "<?php\nnamespace Iopole\\Repository;\n"
        "class FactureRepository {\n"
        "    public function __construct($registry) { parent::__construct($registry, Facture::class); }\n"
        f"{dummy}\n"
        "    public function findValideesParticulierSansLotOn(\\DateTimeInterface $day): array {\n"
        "        return [];\n"
        "    }\n}\n",
    )
    _write(
        repo,
        "config/packages/messenger.yaml",
        "framework:\n  messenger:\n    routing:\n"
        "      Iopole\\Message\\EreportingQuotidienMessage: async\n"
        "    # EreportingQuotidienMessageHandler\n",
    )
    _write(
        repo,
        "tests/MessageHandler/EreportingQuotidienMessageHandlerTest.php",
        "<?php\nclass EreportingQuotidienMessageHandlerTest {\n"
        "    public function testContinueIfLotExists(): void {}\n}\n",
    )

    def fake_fetch(key, repo_root=None, **kwargs):
        return {
            "configured": True,
            "key": key,
            "goal": "E-reporting quotidien",
            "issuetype": "User Story",
            "status": "Review",
            "acceptance_criteria_verbatim": (
                "User story\nEn tant que comptable je génère les lots SIREN.\n\n"
                "Décisions\nUn lot par SIREN et par jour.\n\n"
                "Critères d'acceptation\n- continue si le lot existe déjà\n"
                + ("padding " * 400)
            ),
            "comments": [{"author": "A", "created": "2026-01-01", "body": "hors mission " * 80}],
            "attachments": ["spec.png"],
            "attachment_files": [],
        }

    def boom_ocr(*args, **kwargs):
        raise AssertionError("OCR should not run for a code review without UI")

    original_fetch = gather_mod.jira_provider.fetch
    original_ocr = gather_mod.ocr.read_images
    gather_mod.jira_provider.fetch = fake_fetch
    gather_mod.ocr.read_images = boom_ocr
    try:
        result = run_scout(
            Config(repo_root=repo),
            "Revue de code LYSI-6160 e-reporting quotidien lots SIREN",
            ticket="LYSI-6160",
            sources=[connector],
            no_llm=True,
        )
    finally:
        gather_mod.jira_provider.fetch = original_fetch
        gather_mod.ocr.read_images = original_ocr

    md = result.markdown
    check("connecteur bundle présent", connector in md)
    check("pas fichier nommé absent", "fichier nommé absent" not in md)
    check("pas de section Trous", "## Trous" not in md)
    check("handler quotidien", "EreportingQuotidienMessageHandler" in md)
    check("createAndSubmitLotsOn", "createAndSubmitLotsOn" in md)
    check("continue garde", "continue;" in md)
    check("lignes handler", "createAndSubmitLotsOn" in md and "|" in md)
    check("findValidees", "findValideesParticulierSansLotOn" in md)
    check("routing messenger", "messenger.yaml" in md)
    check("interdit relire retiré du dossier", "Ne pas relire les sources listées" not in md)
    check("contrat relire tronqués", "Relire seulement les paths marqués tronqués" in md)
    check("tronqué annoncé", "Sources tronquées" in md or "tronqué" in md)
    check("méthode repo extraite", "findValideesParticulierSansLotOn" in md)
    check("ticket user story", "User story" in md)
    check("ticket décisions", "Décisions" in md)
    check("commentaire hors mission absent", "hors mission" not in md)
    check("OCR revue non lancée", result.image_count == 0)
    score_case("LYSI-6160", md, result.ready)

    missing = run_scout(
        Config(repo_root=repo),
        "Inventaire local sans ticket.",
        sources=["src/Iopole/Connector/IopoleConnector.php"],
        no_llm=True,
    )
    check(
        "absence vérifiée avec candidats",
        "non trouvé à src/Iopole/Connector/IopoleConnector.php" in missing.markdown,
    )
    check("candidats basename", "lib/facture-electronique-bundle" in missing.markdown)
    check("pas fichier nommé absent seul", "fichier nommé absent" not in missing.markdown)
    check("garde absence", "Ne pas conclure à l'absence" in missing.markdown)
    check("fichier existant hors Trous", "## Trous" not in missing.markdown)


def _utf16_hex(text: str) -> str:
    return "<" + (b"\xfe\xff" + text.encode("utf-16-be")).hex() + ">"


def _build_review_pdf() -> bytes:
    comments = [
        ("fonds de commerce", False),
        ("paie en masse", False),
        ("5 affaires", False),
        ("CPO / LYSI-4127", True),
        ("bulletin de paie", False),
        ("lot quotidien", False),
        ("SIREN manquant", False),
        ("date de paiement", False),
        ("validation CPO", False),
    ]
    annot_ids = list(range(5, 5 + len(comments)))
    annots_ref = " ".join(f"{item} 0 R" for item in annot_ids)
    stream = (
        "BT /F1 12 Tf 72 720 Td (fonds de commerce paie en masse 5 affaires) Tj ET\n"
    ).encode("latin-1")
    page = (
        "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        f"/Contents 4 0 R /Annots [{annots_ref}] /Resources << >> >>\nendobj\n"
    ).encode("ascii")
    contents = (
        f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii")
        + stream
        + b"endstream\nendobj\n"
    )
    chunks = [
        b"%PDF-1.4\n",
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        page,
        contents,
    ]
    for offset, (text, utf16) in enumerate(comments):
        obj_id = 5 + offset
        y = 700 - offset * 18
        payload = _utf16_hex(text) if utf16 else f"({text})"
        chunks.append(
            (
                f"{obj_id} 0 obj\n"
                f"<< /Type /Annot /Subtype /Highlight /P 3 0 R "
                f"/Rect [70 {y} 260 {y + 14}] "
                f"/QuadPoints [70 {y + 14} 260 {y + 14} 70 {y} 260 {y}] "
                f"/Contents {payload} /T (Reviewer) /M (D:20260904120000) >>\n"
                "endobj\n"
            ).encode("latin-1")
        )
    chunks.append(b"trailer\n<< /Root 1 0 R /Size 14 >>\n%%EOF\n")
    return b"".join(chunks)


def _tiny_png() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
    )


def _test_lys_6417() -> None:
    from local_agent.config import Config
    from local_agent.scout import gather as gather_mod
    from local_agent.scout.engine import run_scout
    from local_agent.scout.pdf import extract_annots

    repo = Path(tempfile.mkdtemp())
    folder = "temp/64XX/6417/contexte/pieces_jointes"
    pdf_rel = f"{folder}/REVIEW-Synthese-fonctionnelle-040926.pdf"
    png_rel = f"{folder}/screenshot-voisin.png"
    pdf_bytes = _build_review_pdf()
    _write(repo, pdf_rel, "")
    (repo / pdf_rel).write_bytes(pdf_bytes)
    _write(repo, png_rel, "")
    (repo / png_rel).write_bytes(_tiny_png())

    packed = extract_annots(repo / pdf_rel)
    check("parser 9 highlight", len(packed.get("annots") or []) == 9)
    check("UTF-16 BE Contents", any("LYSI-4127" in (item.get("contents") or "") for item in packed["annots"]))
    check("fonds de commerce", any("fonds de commerce" in (item.get("contents") or "") for item in packed["annots"]))

    def boom_jira(*args, **kwargs):
        raise AssertionError("Jira must not run without ticket=")

    def boom_ocr(*args, **kwargs):
        raise AssertionError("OCR must not run on sibling PNG or the PDF")

    original_fetch = gather_mod.jira_provider.fetch
    original_ocr = gather_mod.ocr.read_images
    gather_mod.jira_provider.fetch = boom_jira
    gather_mod.ocr.read_images = boom_ocr
    try:
        result = run_scout(
            Config(repo_root=repo),
            "Commentaires jaunes de REVIEW-Synthese-fonctionnelle-040926.pdf (LYSI-6417)",
            sources=[pdf_rel],
            no_llm=True,
        )
        folder_result = run_scout(
            Config(repo_root=repo),
            "Commentaires jaunes du dossier pieces_jointes LYSI-6417",
            sources=[folder],
            no_llm=True,
        )
    finally:
        gather_mod.jira_provider.fetch = original_fetch
        gather_mod.ocr.read_images = original_ocr

    md = result.markdown
    check("6417 ready", result.ready is True)
    envelope = _handle(
        "scout",
        {
            "mission": "Commentaires jaunes de REVIEW-Synthese-fonctionnelle-040926.pdf",
            "sources": [pdf_rel],
            "repo": str(repo),
            "use_llm": False,
        },
    )
    check("MCP ready true", envelope.startswith("ready_for_diagnosis: true"))
    check("chemin PDF fidèle", pdf_rel in md)
    check("Highlight présents", "Highlight" in md)
    check("commentaire fonds de commerce", "fonds de commerce" in md)
    check("commentaire paie en masse", "paie en masse" in md)
    check("commentaire 5 affaires", "5 affaires" in md)
    check("commentaire CPO UTF-16", "LYSI-4127" in md)
    check("pas OCR voisin", "screenshot-voisin" not in md)
    check("pas dump Jira", "Tickets" not in md.split("## Mission")[-1][:200] or "## Tickets" not in md)
    check("pas aucun hit rg", "rg 0 match" not in md)
    check("pas Manqué si annots ok", "## Manqué" not in md)
    score_case("LYSI-6417-pdf", md, result.ready)

    folder_md = folder_result.markdown
    check("dossier not ready", folder_result.ready is False)
    check("index dossier", "REVIEW-Synthese-fonctionnelle-040926.pdf" in folder_md)
    check("Trous dossier", "## Trous" in folder_md)
    check("re-read PDF", any(pdf_rel in str(item.get("path")) for item in folder_result.re_read_allowed))
    check("pas OCR du dossier", folder_result.image_count == 0)
    check("pas prêt + ne pas relire", "Ne pas relire les sources listées" not in folder_md)
    score_case("LYSI-6417-dir", folder_md, folder_result.ready)


def _test_lys_6553() -> None:
    from local_agent.config import Config
    from local_agent.scout import gather as gather_mod
    from local_agent.scout.engine import run_scout

    repo = Path(tempfile.mkdtemp())
    _write(
        repo,
        "config/routes/planification.yaml",
        "planification_bons_travaux:\n"
        "  path: /planification-bons-travaux/{salarieId}\n"
        "  controller: App\\Controller\\PlanificationBonsTravauxController::index\n",
    )
    _write(
        repo,
        "src/Controller/PlanificationBonsTravauxController.php",
        "<?php\nnamespace App\\Controller;\n"
        "class PlanificationBonsTravauxController {\n"
        "    public function index(string $salarieId) {\n"
        "        $dureePlanifiee = 0;\n"
        "        return $this->render('planification_bt.html.twig', [\n"
        "            'dureePlanifiee' => $dureePlanifiee,\n"
        "        ]);\n"
        "    }\n}\n",
    )
    _write(
        repo,
        "templates/planification_bt.html.twig",
        "<span class=\"badge\">{{ dureePlanifiee }}</span>\n",
    )
    _write(
        repo,
        "src/Controller/ChantierController.php",
        "<?php\nnamespace App\\Controller;\n"
        "use App\\Service\\PlanificationBonsService;\n"
        "class ChantierController {\n"
        "    public function show(PlanificationBonsService $service) {\n"
        "        return $service->noop();\n"
        "    }\n}\n",
    )
    _write(
        repo,
        "src/Service/PlanificationBonsService.php",
        "<?php\nclass PlanificationBonsService {\n"
        + "\n".join(f"    public function pad{index}(): void {{}}" for index in range(20))
        + "\n    public function reinit(): void {}\n"
        + "    public function estBonAReplanifierNocturne(): bool { return false; }\n}\n",
    )

    salarie = "0194d54a-f05a-7000-8000-000000000001"
    tickets = {
        "LYSI-6553": {
            "configured": True,
            "key": "LYSI-6553",
            "goal": "Durée planifiée à 0h / 0km",
            "issuetype": "Anomalie",
            "status": "Ouvert",
            "fix_versions": [],
            "acceptance_criteria_verbatim": (
                "Écran /planification-bons-travaux/" + salarie + "/\n"
                "durée planifiée à 0, compteur 0km, jauge.\n"
                "planning polyvalents. PlanificationBonsService.\n"
            ),
            "comments": [],
            "attachments": ["oh-okm.png"],
            "attachment_files": [],
        },
        "LYSI-6005": {
            "configured": True,
            "key": "LYSI-6005",
            "goal": "Planning polyvalents",
            "issuetype": "Anomalie",
            "status": "Fermé",
            "fix_versions": ["1.24.12"],
            "acceptance_criteria_verbatim": "MEP 1.24.12 le 29/07/2026.\nCorrige le planning.\n",
            "comments": [{"author": "Dev", "created": "2026-07-29", "body": "livré en 1.24.12"}],
            "attachments": [],
            "attachment_files": [],
        },
        "LYSI-6109": {
            "configured": True,
            "key": "LYSI-6109",
            "goal": "lié 6109",
            "issuetype": "Anomalie",
            "status": "Ouvert",
            "fix_versions": [],
            "acceptance_criteria_verbatim": "Description 6109 ligne 1.\n",
            "comments": [],
            "attachments": [],
            "attachment_files": [],
        },
        "LYSI-1871": {
            "configured": True,
            "key": "LYSI-1871",
            "goal": "lié 1871",
            "issuetype": "Anomalie",
            "status": "Ouvert",
            "fix_versions": [],
            "acceptance_criteria_verbatim": "Description 1871.\n",
            "comments": [],
            "attachments": [],
            "attachment_files": [],
        },
        "LYSI-6130": {
            "configured": True,
            "key": "LYSI-6130",
            "goal": "lié 6130",
            "issuetype": "Anomalie",
            "status": "Ouvert",
            "fix_versions": [],
            "acceptance_criteria_verbatim": "Description 6130.\n",
            "comments": [],
            "attachments": [],
            "attachment_files": [],
        },
        "LYSI-6271": {
            "configured": True,
            "key": "LYSI-6271",
            "goal": "Capture Aurélie",
            "issuetype": "Anomalie",
            "status": "Ouvert",
            "fix_versions": [],
            "acceptance_criteria_verbatim": "Ticket lié 6271, cinq lignes max.\nPas ses pièces.\n",
            "comments": [],
            "attachments": ["CARTAUD-ocr.png"],
            "attachment_files": [
                {
                    "filename": "CARTAUD-ocr.png",
                    "mime": "image/png",
                    "content": "http://example/CARTAUD",
                }
            ],
        },
    }

    def fake_fetch(key, repo_root=None, **kwargs):
        attachments = kwargs.get("attachments", True)
        packed = dict(tickets[key])
        if not attachments:
            packed["attachments"] = []
            packed["attachment_files"] = []
        return packed

    def fake_search(jql, repo_root=None, **kwargs):
        return {
            "configured": True,
            "jql": jql,
            "total": 2,
            "results": [
                {
                    "key": "LYSI-7001",
                    "goal": "durée planifiée 0",
                    "status": "Ouvert",
                    "issuetype": "Anomalie",
                },
                {
                    "key": "LYSI-7002",
                    "goal": "jauge compteur",
                    "status": "Fermé",
                    "issuetype": "Anomalie",
                },
            ],
        }

    def fake_cql(query, repo_root=None, **kwargs):
        return {
            "configured": True,
            "query": query,
            "results": [],
            "error": "Confluence : 0 page pour " + repr(query),
        }

    def boom_ocr(*args, **kwargs):
        raise AssertionError("OCR must not inline CARTAUD from linked 6271")

    original_fetch = gather_mod.jira_provider.fetch
    original_search = gather_mod.jira_provider.search
    original_cql = gather_mod.confluence_provider.search
    original_ocr = gather_mod.ocr.read_images
    gather_mod.jira_provider.fetch = fake_fetch
    gather_mod.jira_provider.search = fake_search
    gather_mod.confluence_provider.search = fake_cql
    gather_mod.ocr.read_images = boom_ocr
    try:
        result = run_scout(
            Config(repo_root=repo),
            (
                "fetch LYSI-6005 LYSI-6109 LYSI-1871 LYSI-6130 LYSI-6271 et chercher un ticket "
                "existant sur le même défaut (compteur/jauge/durée planifiée à 0, planning "
                "polyvalents). ne pas conclure à l'absence sans les résultats."
            ),
            ticket="LYSI-6553",
            sources=[
                "jira://LYSI-6005",
                "jira://LYSI-6109",
                "jira://LYSI-1871",
                "jira://LYSI-6130",
                "jira://LYSI-6271",
            ],
            no_llm=True,
        )
    finally:
        gather_mod.jira_provider.fetch = original_fetch
        gather_mod.jira_provider.search = original_search
        gather_mod.confluence_provider.search = original_cql
        gather_mod.ocr.read_images = original_ocr

    md = result.markdown
    check("6553 recherche Jira", "## Recherche Jira" in md)
    check("6553 JQL présent", "JQL :" in md)
    check("6553 candidats JQL", "LYSI-7001" in md)
    check("6553 pas CARTAUD", "CARTAUD" not in md)
    check("6553 pas OCR lié omitted", "16 additional items omitted" not in md)
    check("6553 ticket primaire", "LYSI-6553" in md)
    check("6553 lié 6005 MEP", "1.24.12" in md)
    check("6553 écran Travaux", "PlanificationBonsTravauxController" in md)
    check("6553 render écran", "planification_bt.html.twig" in md or "dureePlanifiee" in md)
    check(
        "6553 Chantier écarté",
        "ChantierController" not in md or "mention incidente" in md,
    )
    check("6553 salarieId typé", "salarieId" in md)
    check("6553 pas id planif", "ce n'est pas l'id de planification" in md)
    check("6553 UUID salarie", salarie in md)
    check("6553 Confluence section", "## Confluence" in md)
    check("6553 Trous non vide", "## Trous" in md and "- aucun" not in md.split("## Trous", 1)[1][:200])
    check("6553 pas ready", result.ready is False)
    headings = [
        "## Mission",
        "## Ticket",
        "## Tickets liés demandés",
        "## Recherche Jira",
        "## Code",
        "## Confluence",
        "## Trous",
        "## À l'orchestrateur",
    ]
    indexes = [md.index(item) for item in headings]
    check("6553 ordre sections", indexes == sorted(indexes))
    check("6553 orchestrateur SQL", "SQL" in md.split("## À l'orchestrateur")[-1])
    score_case("LYSI-6553-c2", md, result.ready)


def _test_logs_extract() -> None:
    from local_agent.scout import logs as log_x

    phpunit = (
        "PHPUnit 10.5\n"
        + "...F...E..\n" * 3
        + "\n"
        + "Time: 00:04.221, Memory: 24.00 MB\n\n"
        + "There were 2 failures:\n\n"
        + "1) App\\Tests\\PaieServiceTest::testComputeTotalReturnsNullWhenQtyZero\n"
        + "Failed asserting that null matches expected 0.\n"
        + "/app/src/PaieService.php:88\n"
        + "/app/tests/PaieServiceTest.php:42\n\n"
        + "FAILURES!\n"
        + "Tests: 120, Assertions: 340, Failures: 2.\n"
    )
    packed = log_x.extract_failures(phpunit)
    check("logs: signal détecté", packed["match_count"] > 0)
    check("logs: méthode en échec gardée", "testComputeTotalReturnsNullWhenQtyZero" in packed["kept"])
    check("logs: chemin fichier gardé", "PaieService.php:88" in packed["kept"])
    check("logs: dots répétés dédupliqués", packed["kept"].count("...F...E..") <= 1)
    check("logs: total_lines posé", packed["total_lines"] == len(phpunit.splitlines()))

    clean = "\n".join(f"ok {index}" for index in range(200))
    packed_clean = log_x.extract_failures(clean)
    check("logs: pas de signal -> queue seulement", packed_clean["match_count"] == 0)
    check("logs: queue bornée", packed_clean["kept_lines"] <= 40)
    check("logs: queue = fin du log", "ok 199" in packed_clean["kept"])
    check("logs: queue annoncée tronquée si log plus long", packed_clean["truncated"] is True)

    blocks = []
    for index in range(60):
        blocks.append(f"{index + 1}) Foo::testBar{index}")
        blocks.append(f"AssertionError: boom {index}")
        blocks.append("padding " * 5)
    big_failure = "\n".join(blocks)
    packed_big = log_x.extract_failures(big_failure, max_chars=500)
    check("logs: plafond respecté", len(packed_big["kept"]) <= 520)
    check("logs: plafond annoncé", packed_big["truncated"] is True)

    check("logs: vide", log_x.extract_failures("")["kept"] == "")


def _git(repo: Path, *args: str) -> str:
    import subprocess

    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    process = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return process.stdout


def _make_git_fixture() -> Path:
    repo = Path(tempfile.mkdtemp())
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, "README.md", "root\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "feature/LYSI-9001-fix")
    _write(repo, "src/fix.txt", "fix\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "LYSI-9001: fix the thing")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge LYSI-9001", "feature/LYSI-9001-fix")
    _git(repo, "checkout", "-q", "-b", "feature/LYSI-9002-wip")
    _write(repo, "src/wip.txt", "wip\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "LYSI-9002: still in progress")
    _git(repo, "checkout", "-q", "main")
    return repo


def _test_gitarch() -> None:
    from local_agent.scout import gitarch

    repo = _make_git_fixture()
    merged = gitarch.find_branches("LYSI-9001", repo)
    check("gitarch: pas d'erreur", merged["error"] is None)
    check("gitarch: branche mergée trouvée", "feature/LYSI-9001-fix" in [b["branch"] for b in merged["branches"]])
    merged_branch = next(b for b in merged["branches"] if b["branch"] == "feature/LYSI-9001-fix")
    check("gitarch: main détectée", "main" in merged["main_branches"])
    check("gitarch: statut mergé", "main" in merged_branch["merged_into"])
    check("gitarch: trouvée par historique", merged_branch["matched_history"] is True)

    wip = gitarch.find_branches("LYSI-9002", repo)
    wip_branch = next(b for b in wip["branches"] if b["branch"] == "feature/LYSI-9002-wip")
    check("gitarch: branche non mergée détectée", wip_branch["merged_into"] == [])
    check("gitarch: trouvée par nom", wip_branch["matched_name"] is True)

    absent = gitarch.find_branches("LYSI-0000-nexistepas", repo)
    check("gitarch: aucun candidat", absent["branches"] == [])
    check("gitarch: 0 commit au message", absent["commit_matches"] == 0)

    not_a_repo = gitarch.find_branches("LYSI-1", Path(tempfile.mkdtemp()))
    check("gitarch: pas un dépôt git signalé", not_a_repo["error"] is not None)


def _test_gather_log_source() -> None:
    from local_agent.config import Config
    from local_agent.scout.engine import run_scout

    repo = Path(tempfile.mkdtemp())
    progress_noise = "\n".join("...........F........." for _ in range(200))
    _write(
        repo,
        "var/log/paratest.log",
        "Running 40 tests\n"
        + progress_noise
        + "\n\n1) App\\Tests\\PaieServiceTest::testComputeTotal\n"
        + "Failed asserting that 0 matches expected 12.\n"
        + "/app/src/PaieService.php:88\n\nFAILURES!\n",
    )
    result = run_scout(
        Config(repo_root=repo),
        "CI en échec, diagnostiquer.",
        sources=["log://var/log/paratest.log"],
        no_llm=True,
    )
    check("gather log://: section Logs", "## Logs" in result.markdown)
    check("gather log://: échec conservé", "testComputeTotal" in result.markdown)
    check(
        "gather log://: bruit hors contexte exclu",
        result.markdown.count("...........F.........") < 5,
    )
    check("gather log://: bien plus petit que le log source", len(result.markdown) < len(progress_noise))

    missing = run_scout(
        Config(repo_root=repo),
        "Log absent.",
        sources=["log://var/log/introuvable.log"],
        no_llm=True,
    )
    check("gather log://: absent -> Trous", "introuvable.log" in missing.markdown)


def _test_gather_git_source() -> None:
    from local_agent.config import Config
    from local_agent.scout.engine import run_scout

    repo = _make_git_fixture()
    result = run_scout(
        Config(repo_root=repo),
        "Quelle branche porte LYSI-9001, est-elle fusionnée ?",
        sources=["git://LYSI-9001"],
        no_llm=True,
    )
    check("gather git://: section Branches", "## Branches" in result.markdown)
    check("gather git://: branche listée", "feature/LYSI-9001-fix" in result.markdown)
    check("gather git://: statut fusion", "fusionnée dans : main" in result.markdown)
    check(
        "gather git://: main pas rendu 'non fusionnée'",
        "`main` — " in result.markdown and "branche principale" in result.markdown,
    )


def _test_ticket_truncation_flagged() -> None:
    """LYSI-6591 terrain : ce qui est coupé à l'affichage doit rester relisible, et dit."""
    long_body = "\n".join(
        ["Décisions", *[f"- étape {index} : transformer le champ X{index} en Y{index}" for index in range(200)]]
    )
    long_dossier = Dossier(mission="Intervention en prod : flux donnée")
    long_dossier.tickets.append(
        {
            "key": "LYSI-6591",
            "goal": "flux donnée",
            "issuetype": "Intervention",
            "status": "Ouvert",
            "acceptance_criteria_verbatim": long_body,
            "comments": [],
        }
    )
    long_md = long_dossier.markdown()
    check("ticket long : re-read_allowed rempli", any(
        "LYSI-6591" in str(item.get("path")) for item in long_dossier.re_read_allowed
    ))
    check("ticket long : re-read_allowed dans le header", "jira://LYSI-6591" in long_md)
    check("ticket long : partie coupée nommée", "description" in long_md.split("## Mission")[0])

    medium = "\n".join(f"ligne {index} du constat métier détaillé" for index in range(30))
    medium_dossier = Dossier(mission="Extraire LYSI-2")
    medium_dossier.tickets.append(
        {"key": "LYSI-2", "goal": "t", "issuetype": "Anomalie", "status": "Ouvert",
         "acceptance_criteria_verbatim": medium, "comments": []}
    )
    medium_md = medium_dossier.markdown()
    check("ticket moyen : corps intégral", "ligne 29 du constat" in medium_md)
    check("ticket moyen : rien à relire", medium_dossier.re_read_allowed == [])

    short_dossier = Dossier(mission="Petit ticket")
    short_dossier.tickets.append(
        {
            "key": "LYSI-1",
            "goal": "titre",
            "issuetype": "Anomalie",
            "status": "Ouvert",
            "acceptance_criteria_verbatim": "Décisions\n- une seule ligne courte",
            "comments": [],
        }
    )
    short_dossier.markdown()
    check("ticket court : pas de re-read_allowed", short_dossier.re_read_allowed == [])


def _test_extraction_mission() -> None:
    """Sessions /analyse du 29/09 au 01/10 : « Extraire… » doit rendre un ticket complet et prêt."""
    import subprocess

    from local_agent.config import Config
    from local_agent.providers import atlassian
    from local_agent.scout import gather as gather_mod
    from local_agent.scout.dossier import _ocr_text
    from local_agent.scout.engine import run_scout

    repo = Path(tempfile.mkdtemp())
    _write(repo, "src/Controller/PlanificationBonsTravauxController.php", "<?php\nclass X { function a(){ return $this->render('a'); } }\n")

    def fake_fetch(key, repo_root=None, **kwargs):
        return {
            "configured": True,
            "key": key,
            "goal": "RH PAIE / MORLAIX / Contrat introuvable",
            "issuetype": "Intervention en prod",
            "status": "Nouveau",
            "priority": "Haute",
            "acceptance_criteria_verbatim": "\n".join(f"constat ligne {index}" for index in range(25)),
            "comments": [{"author": "Diana", "created": "2026-09-29", "body": "COMMENT-PROOF avenant du 24/09"}],
            "comment_total": 1,
            "links": [{"key": "LYSI-6400", "relation": "relates to", "goal": "avenants", "status": "En cours"}],
            "custom_fields": [{"name": "Analyse 6TM", "text": "FIELD-PROOF donnée incohérente en base"}],
            "attachments": ["image-1.png", "export.xlsx"],
            "attachment_files": [],
        }

    def boom_search(*args, **kwargs):
        raise AssertionError("Confluence non demandée par une mission d'extraction")

    original_fetch = gather_mod.jira_provider.fetch
    original_cql = gather_mod.confluence_provider.search
    gather_mod.jira_provider.fetch = fake_fetch
    gather_mod.confluence_provider.search = boom_search
    try:
        result = run_scout(
            Config(repo_root=repo),
            "Extraire issuetype exact, titre, statut, constat, attendu, commentaires utiles, liens et pièces, "
            "champs Analyse 6TM et Analyse ABER. LYSI-6591",
            ticket="LYSI-6591",
            no_llm=True,
        )
    finally:
        gather_mod.jira_provider.fetch = original_fetch
        gather_mod.confluence_provider.search = original_cql
    md = result.markdown
    check("extraction : prêt", result.ready is True)
    check("extraction : corps intégral", "constat ligne 24" in md)
    check("extraction : priorité", "Priorité : Haute" in md)
    check("extraction : champ personnalisé", "FIELD-PROOF" in md and "Analyse 6TM" in md)
    check("extraction : commentaire", "COMMENT-PROOF" in md)
    check("extraction : lien", "LYSI-6400" in md)
    check("extraction : pièce non lue signalée", "non lues par scout : export.xlsx" in md)
    check("extraction : pas de code hors sujet", "## Code" not in md)
    check("extraction : pas de Confluence imposée", "## Confluence" not in md)
    check("extraction : pas de trou fantôme", "non cherchée" not in md)

    from local_agent.scout.dossier import _page_block

    page_dossier = Dossier(mission="Citer la page")
    page_dossier.pages.append(
        {"id": "2505965569", "title": "Recette", "body": "PAGE-START " + "règle " * 1200 + " PAGE-END", "full_path": "temp/scout/x/pages/2505965569.md"}
    )
    page_md = page_dossier.markdown()
    check("page : corps rendu au-delà de 400 caractères", len(_page_block(page_dossier.pages[0])[0]) > 3000)
    check("page : coupe signalée avec fichier", "confluence://2505965569" in page_md and "pages/2505965569.md" in page_md)
    check("écran décrit par une capture n'exige pas de code", extract.wants_screen("Lire les captures, écran Journaux Quadra") is False)
    check("chemin absolu conservé", extract.as_repo_path("/abs/dir/image-1.png") == "/abs/dir/image-1.png")
    check("chercher dans Confluence n'est pas un JQL", extract.wants_jira_search("Chercher dans Confluence la doc") is False)
    check(
        "requête Confluence = domaine du titre",
        extract.confluence_query("Extraire issuetype exact", "", "RH PAIE / MORLAIX / Contrat introuvable")
        == "Contrat introuvable",
    )
    text, cut = _ocr_text("|  | Taux | 12.57 |  |\n|  |  |  |\n| Rémunération | 1885.26 |\n")
    check("OCR : chiffres gardés sans mot-clé", "12.57" in text and "1885.26" in text and cut is False)
    check("OCR : cellules vides retirées", "|  |" not in text)

    from local_agent.providers import jira as jira_mod

    names = {
        "customfield_1": "Analyse 6TM", "customfield_2": "Analyse ABER", "customfield_3": "development",
        "customfield_4": "Date dernier commentaire", "customfield_5": "Attendu",
    }
    raw_fields = {
        "customfield_1": None,
        "customfield_2": {"value": "Anomalie de TMA"},
        "customfield_3": "{repository={count=1, dataType=repository}}",
        "customfield_4": "Tue Sep 29 15:13:02 UTC 2026",
        "customfield_5": "Le contrat doit rester visible après modification",
    }
    texts = [field["name"] for field in jira_mod._custom_fields(raw_fields, names)]
    check("jira : champ rédigé gardé, bruit technique écarté", texts == ["Attendu"])
    check("jira : champ à choix lu", jira_mod._option_fields(raw_fields, names) == [{"name": "Analyse ABER", "text": "Anomalie de TMA"}])
    check("jira : champ vide nommé", jira_mod._empty_field_names(raw_fields, names) == ["Analyse 6TM"])

    main_repo = Path(tempfile.mkdtemp()).resolve()
    subprocess.run(["git", "init", "-q", "-b", "main", str(main_repo)], check=True)
    _git(main_repo, "commit", "-q", "--allow-empty", "-m", "init")
    _write(main_repo, ".claude/.env.local", "JIRA_URL=https://example.atlassian.net\nJIRA_API_TOKEN=tok\n")
    worktree = main_repo.parent / (main_repo.name + "-wt")
    _git(main_repo, "worktree", "add", "-q", str(worktree))
    saved = {key: os.environ.pop(key, None) for key in atlassian._KEYS}
    try:
        creds = atlassian.credentials(worktree)
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
    check("worktree : credentials du checkout principal", creds["base"] == "https://example.atlassian.net")


def _test_maybe_vision() -> None:
    """OCR seul ne suffit pas sur certaines captures : seconde passe vision, opt-in, bornée."""
    from local_agent.config import Config
    from local_agent.mlx import Completion
    from local_agent.scout import engine as engine_mod
    from local_agent.scout.dossier import Dossier

    class FakeVisionClient:
        complete_calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def models(self):
            return ["qwen-vl"]

        def supports_vision(self):
            return True

        def complete(self, prompt, system, **kwargs):
            FakeVisionClient.complete_calls += 1
            payload = json.dumps(
                {
                    "notes": ["colonne Statut fusionnée sur deux lignes"],
                    "ui": ["bouton Valider désactivé"],
                    "header_split": ["Nom", "Statut", "Date"],
                }
            )
            return Completion(text=payload, prompt_tokens=10, completion_tokens=20)

    tmp = Path(tempfile.mkdtemp())
    image_path = tmp / "capture.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    dossier = Dossier(mission="Revue de l'écran, colonne fusionnée ?")
    dossier.images.append({"name": "capture.png", "path": str(image_path), "transcript": ""})
    FakeVisionClient.complete_calls = 0
    engine_mod._maybe_vision(Config(repo_root=tmp), dossier, FakeVisionClient())
    check("vision: appelée sur trou de layout", FakeVisionClient.complete_calls == 1)
    check(
        "vision: notes récupérées",
        dossier.images[0].get("vision_notes") == ["colonne Statut fusionnée sur deux lignes"],
    )
    md = dossier.markdown()
    check("vision: rendu dans les Captures", "Vision locale" in md)
    check("vision: UI rendue", "bouton Valider désactivé" in md)

    dossier2 = Dossier(mission="Lister les montants affichés")
    dossier2.images.append(
        {"name": "cap2.png", "path": str(image_path), "transcript": "Montant: 120,50 € " * 5}
    )
    FakeVisionClient.complete_calls = 0
    engine_mod._maybe_vision(Config(repo_root=tmp), dossier2, FakeVisionClient())
    check("vision: pas d'appel si OCR déjà suffisant", FakeVisionClient.complete_calls == 0)

    class NoVisionClient:
        def models(self):
            return ["qwen"]

        def complete(self, *args, **kwargs):
            raise AssertionError("ne doit pas être appelé sans supports_vision")

    dossier3 = Dossier(mission="Revue, colonne fusionnée ?")
    dossier3.images.append({"name": "cap3.png", "path": str(image_path), "transcript": ""})
    engine_mod._maybe_vision(Config(repo_root=tmp), dossier3, NoVisionClient())
    check("vision: client sans supports_vision ignoré", "vision_notes" not in dossier3.images[0])


def _test_gitlab_provider() -> None:
    import os

    from local_agent.providers import gitlab as gitlab_provider

    repo = Path(tempfile.mkdtemp())
    saved = {key: os.environ.pop(key, None) for key in gitlab_provider._KEYS}
    try:
        not_configured = gitlab_provider.fetch_trace("123", repo_root=repo)
        check("gitlab: projet manquant signalé", "not configured" in (not_configured.get("error") or ""))

        os.environ["GITLAB_URL"] = "https://gitlab.example.com"
        os.environ["GITLAB_PROJECT_ID"] = "42"
        no_token = gitlab_provider.fetch_trace("123", repo_root=repo)
        check("gitlab: token manquant signalé", "GITLAB_TOKEN" in (no_token.get("error") or ""))

        os.environ["GITLAB_TOKEN"] = "secret"
        creds = gitlab_provider.credentials(repo)
        check("gitlab: credentials résolus", creds == {"base": "https://gitlab.example.com", "token": "secret", "project": "42"})
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)


if __name__ == "__main__":
    main()

