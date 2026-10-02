"""Cas terrain LYSI-6160 / 6417 / 6553 : prompts de chat et grille d'évaluation.

Le score porte sur le dossier scout, pas sur les cartes Cursor.
Mode fixture = tests. Mode live = dépôt client + Jira réel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Check:
    id: str
    kind: str
    needle: str
    weight: int = 1
    when: str = "any"
    label: str = ""


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    ticket: str | None
    mission: str
    sources: list[str]
    prompt: str
    checks: list[Check]
    expect_ready: bool | None = None
    glob_basename: str | None = None
    calls: int = 1
    folder: bool = False


@dataclass
class CheckHit:
    id: str
    label: str
    ok: bool
    weight: int
    detail: str = ""


@dataclass
class Score:
    case_id: str
    passed: int
    total: int
    weighted_ok: int
    weighted: int
    hits: list[CheckHit] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    ready: bool | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def pct(self) -> float:
        if not self.weighted:
            return 0.0
        return round(100.0 * self.weighted_ok / self.weighted, 1)

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.passed == self.total


def _body(text: str) -> tuple[str, bool | None]:
    raw = text or ""
    ready = None
    head = raw.split("---", 1)[0] if raw.startswith("ready_for_diagnosis:") else ""
    if head:
        if "ready_for_diagnosis: true" in head:
            ready = True
        elif "ready_for_diagnosis: false" in head:
            ready = False
        raw = raw.split("---", 1)[-1]
    return raw, ready


def score_markdown(text: str, case: Case, *, mode: str = "live", ready: bool | None = None) -> Score:
    body, envelope_ready = _body(text)
    got_ready = envelope_ready if envelope_ready is not None else ready
    hits: list[CheckHit] = []
    skipped: list[str] = []
    for check in case.checks:
        if check.when not in {"any", mode}:
            skipped.append(check.id)
            continue
        ok = False
        detail = ""
        if check.kind == "contains":
            ok = check.needle in body
            detail = "présent" if ok else f"absent : {check.needle[:80]}"
        elif check.kind == "absent":
            ok = check.needle not in body
            detail = "absent OK" if ok else f"fuite : {check.needle[:80]}"
        elif check.kind == "regex":
            ok = bool(re.search(check.needle, body, re.I | re.M))
            detail = "match" if ok else f"pas de match : {check.needle[:80]}"
        elif check.kind == "section":
            ok = f"## {check.needle}" in body
            detail = f"## {check.needle}" if ok else f"section manquante : {check.needle}"
        elif check.kind == "heading_order":
            last = -1
            ok = True
            missing = []
            for name in check.needle.split("|"):
                idx = body.find(f"## {name}")
                if idx < 0:
                    ok = False
                    missing.append(name)
                    continue
                if idx < last:
                    ok = False
                    missing.append(f"{name} hors ordre")
                last = idx
            detail = "ordre OK" if ok else " · ".join(missing)
        elif check.kind == "ready":
            want = check.needle.strip().lower() == "true"
            if got_ready is None:
                ok = False
                detail = "ready inconnu"
            else:
                ok = got_ready is want
                detail = f"ready={got_ready} (attendu {want})"
        elif check.kind == "trous_non_vide":
            if "## Trous" not in body:
                ok = False
                detail = "pas de section Trous"
            else:
                chunk = body.split("## Trous", 1)[1].split("## ", 1)[0]
                ok = "- aucun" not in chunk[:200]
                detail = "Trous renseignés" if ok else "Trous : aucun (interdit ici)"
        else:
            detail = f"kind inconnu {check.kind}"
        hits.append(
            CheckHit(
                id=check.id,
                label=check.label or check.id,
                ok=ok,
                weight=check.weight,
                detail=detail,
            )
        )
    passed = sum(1 for item in hits if item.ok)
    weighted_ok = sum(item.weight for item in hits if item.ok)
    weighted = sum(item.weight for item in hits)
    notes = []
    if case.expect_ready is not None and got_ready is not None and got_ready is not case.expect_ready:
        notes.append(f"ready={got_ready}, attendu {case.expect_ready}")
    return Score(
        case_id=case.id,
        passed=passed,
        total=len(hits),
        weighted_ok=weighted_ok,
        weighted=weighted,
        hits=hits,
        skipped=skipped,
        ready=got_ready,
        notes=notes,
    )


def resolve_sources(repo: Path, case: Case) -> tuple[list[str], str | None]:
    found: list[str] = []
    for item in case.sources:
        path = repo / item
        if path.exists():
            found.append(item)
            continue
        if item.lower().startswith("jira://"):
            found.append(item)
            continue
        name = case.glob_basename or Path(item).name
        hits = sorted(path for path in repo.rglob(name) if path.is_file())
        if not hits:
            return [], f"{item} introuvable sous {repo}"
        hit = hits[0].parent if case.folder else hits[0]
        try:
            found.append(str(hit.resolve().relative_to(repo.resolve())))
        except ValueError:
            found.append(str(hit))
    return found, None


def get_case(ident: str) -> Case:
    key = (ident or "").strip()
    if key not in CASES:
        known = ", ".join(CASES)
        raise ValueError(f"cas inconnu {ident!r}. Disponibles : {known}")
    return CASES[key]


PROMPT_6160 = """\
Nouveau chat. Dépôt LYSI (pas ~/.local-scout). MCP user-local-scout ON. Relancer le serveur si la version n'est pas 1.8.x.

Tu es l'orchestrateur. Scout est un FILTRE de sources lourdes. Il ne diagnostique pas.
Un seul appel `scout`. use_llm=false. Ne pas curl Jira, ne pas Read le connecteur en entier.

Revue de code LYSI-6160 : e-reporting quotidien, lots SIREN.
Ne corrige pas. Qualifie ensuite.

Appelle exactement :

scout(
  mission="Revue de code LYSI-6160 e-reporting quotidien lots SIREN. Extraire le handler quotidien, createAndSubmitLotsOn + continue si le lot existe, findValideesParticulierSansLotOn, routing messenger.yaml.",
  ticket="LYSI-6160",
  sources=["lib/facture-electronique-bundle/src/Iopole/Connector/IopoleConnector.php"],
  use_llm=false
)

Depuis le dossier :
- Trancher / qualifier. Relire seulement les paths marqués tronqués ou re-read_allowed.
- Vérifier au grep les comptages. Ne pas conclure à l'absence sans Locations.

Fin de chat — scorecard (oui/non) :
- chemin lib/facture-electronique-bundle conservé, pas « fichier nommé absent »
- EreportingQuotidienMessageHandler, createAndSubmitLotsOn, continue, findValideesParticulierSansLotOn, messenger.yaml
- pas de section Trous inventée ; troncature annoncée si le fichier n'est pas intégral
- 0 fallback Read/curl hors Trous
"""

PROMPT_6417_PDF = """\
Nouveau chat. Dépôt LYSI. MCP user-local-scout ON, version 1.8.x.

Tu es l'orchestrateur. Scout filtre. use_llm=false. Un seul appel.
Ne pas OCR le PDF comme une capture. Ne pas OCR les PNG du même dossier.
Ne pas fetch Jira : ticket= n'est pas fourni.

Mission : extraire les commentaires jaunes (Annot Highlight) du PDF de revue LYSI-6417.
Ne pas diagnostiquer le métier. Lister les annots (auteur, page, /Contents).

Appelle exactement :

scout(
  mission="Commentaires jaunes de REVIEW-Synthese-fonctionnelle-040926.pdf (LYSI-6417). Extraire les Annot Highlight, pas l'OCR du PDF.",
  sources=["temp/64XX/6417/contexte/pieces_jointes/REVIEW-Synthese-fonctionnelle-040926.pdf"],
  use_llm=false
)

Si le chemin exact n'existe pas, passe le chemin réel du même fichier (basename identique), pas le dossier parent.

Depuis le dossier : recopie les annots. Pas de Jira. Pas de screenshot voisin.

Fin de chat — scorecard :
- ready_for_diagnosis true s'il y a des Annot, false sinon avec Trous
- Highlight /Contents présents ; chemin PDF fidèle
- pas d'OCR voisin, pas de dump ticket
- 0 Read PNG, 0 curl Jira
"""

PROMPT_6417_DIR = """\
Nouveau chat. Dépôt LYSI. MCP user-local-scout ON.

Même mission LYSI-6417, mais `sources` est le DOSSIER, pas le PDF.
Scout doit indexer, pas extraire les Annot. ready_for_diagnosis: false, section Trous, re-read_allowed vers le PDF.

scout(
  mission="Commentaires jaunes du dossier pieces_jointes LYSI-6417. Extraire les Annot du PDF.",
  sources=["temp/64XX/6417/contexte/pieces_jointes"],
  use_llm=false
)

Si le dossier a bougé, passe le dossier qui contient REVIEW-Synthese-fonctionnelle-040926.pdf.

Scorecard :
- index avec le nom du PDF
- ready false ; Trous / re-read_allowed vers le fichier PDF
- pas d'OCR des PNG du dossier
"""

PROMPT_6553_C1 = """\
Nouveau chat. Dépôt LYSI. MCP user-local-scout ON, version 1.8.x.

Tu es l'orchestrateur. Scout filtre. use_llm=false. Un seul appel pour CET échange.
Ne pas diagnostiquer à la place du dossier. Ne pas curl search/jql. Ne pas Read des PNG.

Diagnostiquer LYSI-6553 (durée planifiée / compteur / jauge à 0, planning polyvalents).
Ne pas corriger. Qualifier ensuite.

Appelle exactement :

scout(
  mission="Diagnostiquer LYSI-6553 : durée planifiée, compteur ou jauge à 0 sur le planning des polyvalents. Rassembler ticket, captures, écran (contrôleur qui render), page Confluence du domaine, UUID d'URL typés. Ne pas conclure à l'absence sans Trous.",
  ticket="LYSI-6553",
  use_llm=false
)

Depuis le dossier :
- L'écran attendu est PlanificationBonsTravauxController (render planification_bt / dureePlanifiee), pas un autre contrôleur qui use() PlanificationBonsService.
- Chaque UUID d'URL : valeur | :paramètreDeRoute | entité. Si :salarieId → ce n'est pas l'id de planification.
- Captures : tableau court + « OCR bruit ». Pas de roman OCR.
- « Trous : aucun » seulement si ticket + Confluence + écran render + UUID typés.
- Mesurer encore (SQL, grep, rejeu) toi-même. Scout ne compte pas (« N journées », « 71 plannings »).

Fin de chat — scorecard :
- ## Ticket compact (type, statut, ≤ 8 lignes, UUID typés)
- écran TravauxController, pas ChantierController comme écran
- Confluence (titre+pageId+citation) OU Trous « non cherchée »
- pas ready_for_diagnosis true si un trou bloquant n'est pas dans Trous
- 0 curl Jira, 0 Read PNG
"""

PROMPT_6553_C2 = """\
Nouveau chat, suite de LYSI-6553. Dépôt LYSI. MCP user-local-scout ON.
N'importe PAS le dossier de l'appel 1. Un seul appel scout. use_llm=false.

La mission contient FETCH des tickets liés ET une RECHERCHE d'un ticket existant
sur le même défaut. Scout doit faire le JQL même si `sources` est rempli.
Ne pas curl /rest/api/3/search/jql. Ne pas inliner l'OCR du ticket lié 6271 (CARTAUD).

Appelle exactement :

scout(
  mission="fetch LYSI-6005 LYSI-6109 LYSI-1871 LYSI-6130 LYSI-6271 et chercher un ticket existant sur le même défaut (compteur/jauge/durée planifiée à 0, planning polyvalents). ne pas conclure à l'absence sans les résultats.",
  ticket="LYSI-6553",
  sources=["jira://LYSI-6005", "jira://LYSI-6109", "jira://LYSI-1871", "jira://LYSI-6130", "jira://LYSI-6271"],
  use_llm=false
)

Le dossier DOIT contenir ## Recherche Jira (JQL, N, ≤ 5 candidats, ou « non exécutée : … »).
Trous non vide tant que Confluence et le typage salarieId/planif n'y sont pas.
LYSI-6005 : résumé + fixVersions (MEP 1.24.12) sans pièces.
CARTAUD / dump OCR 6271 : interdit.

Fin de chat — scorecard :
- ## Recherche Jira avec JQL, même si 0 candidat
- pas CARTAUD, pas « 16 additional items omitted » d'OCR lié
- UUID :salarieId + « ce n'est pas l'id de planification »
- PlanificationBonsTravauxController ; Chantier écarté ou « mention incidente »
- ## Trous non vide (pas « aucun ») si Confluence absente
- 0 curl search/jql
"""


def _c(*args: Check) -> list[Check]:
    return list(args)


CASES: dict[str, Case] = {
    "LYSI-6160": Case(
        id="LYSI-6160",
        title="Revue e-reporting — chemins bundle PHP",
        ticket="LYSI-6160",
        mission=(
            "Revue de code LYSI-6160 e-reporting quotidien lots SIREN. "
            "Extraire le handler quotidien, createAndSubmitLotsOn + continue si le lot existe, "
            "findValideesParticulierSansLotOn, routing messenger.yaml."
        ),
        sources=["lib/facture-electronique-bundle/src/Iopole/Connector/IopoleConnector.php"],
        prompt=PROMPT_6160,
        expect_ready=True,
        checks=_c(
            Check("path_bundle", "contains", "lib/facture-electronique-bundle", 2, label="chemin bundle fidèle"),
            Check("no_false_absent", "absent", "fichier nommé absent", 2, label="pas de faux absent"),
            Check("handler", "contains", "EreportingQuotidienMessageHandler", 2, label="handler quotidien"),
            Check("submit", "contains", "createAndSubmitLotsOn", 2, label="createAndSubmitLotsOn"),
            Check("continue", "contains", "continue", 1, label="continue"),
            Check("find_validees", "contains", "findValideesParticulierSansLotOn", 2, label="findValidees"),
            Check("messenger", "contains", "messenger.yaml", 1, label="routing messenger"),
            Check("no_forbid_reread", "absent", "Ne pas relire les sources listées", 1, label="contrat relire"),
            Check("reread_trunc", "contains", "Relire seulement les paths marqués tronqués", 1, label="troncature honnête"),
            Check("no_trous", "absent", "## Trous", 1, when="fixture", label="pas de Trous fantôme"),
        ),
    ),
    "LYSI-6417-pdf": Case(
        id="LYSI-6417-pdf",
        title="Annot PDF — fichier listé",
        ticket=None,
        mission=(
            "Commentaires jaunes de REVIEW-Synthese-fonctionnelle-040926.pdf (LYSI-6417). "
            "Extraire les Annot Highlight, pas l'OCR du PDF."
        ),
        sources=["temp/64XX/6417/contexte/pieces_jointes/REVIEW-Synthese-fonctionnelle-040926.pdf"],
        glob_basename="REVIEW-Synthese-fonctionnelle-040926.pdf",
        prompt=PROMPT_6417_PDF,
        expect_ready=True,
        checks=_c(
            Check("pdf_name", "contains", "REVIEW-Synthese-fonctionnelle-040926.pdf", 2, label="chemin PDF"),
            Check("highlight", "regex", r"Highlight|Annots PDF", 2, label="Annot extraits"),
            Check("no_neighbor", "absent", "screenshot-voisin", 2, label="pas OCR voisin"),
            Check("no_tickets_heading", "absent", "## Tickets", 1, label="pas dump Jira"),
            Check("ready_true", "ready", "true", 2, label="ready true"),
            Check("fonds", "contains", "fonds de commerce", 1, when="fixture", label="Highlight fonds de commerce"),
            Check("cpo", "contains", "LYSI-4127", 1, when="fixture", label="UTF-16 CPO"),
        ),
    ),
    "LYSI-6417-dir": Case(
        id="LYSI-6417-dir",
        title="Annot PDF — dossier = index",
        ticket=None,
        mission="Commentaires jaunes du dossier pieces_jointes LYSI-6417. Extraire les Annot du PDF.",
        sources=["temp/64XX/6417/contexte/pieces_jointes"],
        glob_basename="REVIEW-Synthese-fonctionnelle-040926.pdf",
        prompt=PROMPT_6417_DIR,
        expect_ready=False,
        folder=True,
        checks=_c(
            Check("index_pdf", "contains", "REVIEW-Synthese-fonctionnelle-040926.pdf", 2, label="PDF dans l'index"),
            Check("trous", "section", "Trous", 2, label="section Trous"),
            Check("ready_false", "ready", "false", 2, label="ready false"),
            Check("no_captures", "absent", "## Captures", 1, label="pas OCR dossier"),
        ),
    ),
    "LYSI-6553-c1": Case(
        id="LYSI-6553-c1",
        title="Diagnostic 6553 — appel 1",
        ticket="LYSI-6553",
        mission=(
            "Diagnostiquer LYSI-6553 : durée planifiée, compteur ou jauge à 0 sur le planning "
            "des polyvalents. Rassembler ticket, captures, écran (contrôleur qui render), "
            "page Confluence du domaine, UUID d'URL typés. Ne pas conclure à l'absence sans Trous."
        ),
        sources=[],
        prompt=PROMPT_6553_C1,
        expect_ready=False,
        checks=_c(
            Check("ticket_h", "section", "Ticket", 1, label="## Ticket"),
            Check("key", "contains", "LYSI-6553", 2, label="clé primaire"),
            Check("screen", "contains", "PlanificationBonsTravauxController", 2, when="live", label="écran Travaux"),
            Check("no_causal", "absent", "le bug vient de", 1, label="pas de synthèse causale"),
            Check("confluence_or_hole", "regex", r"## Confluence|non cherch", 1, label="Confluence ou trou"),
            Check("no_cartaud", "absent", "CARTAUD", 2, label="pas OCR 6271"),
        ),
    ),
    "LYSI-6553-c2": Case(
        id="LYSI-6553-c2",
        title="Fetch liés + JQL — appel 2",
        ticket="LYSI-6553",
        mission=(
            "fetch LYSI-6005 LYSI-6109 LYSI-1871 LYSI-6130 LYSI-6271 et chercher un ticket "
            "existant sur le même défaut (compteur/jauge/durée planifiée à 0, planning "
            "polyvalents). ne pas conclure à l'absence sans les résultats."
        ),
        sources=[
            "jira://LYSI-6005",
            "jira://LYSI-6109",
            "jira://LYSI-1871",
            "jira://LYSI-6130",
            "jira://LYSI-6271",
        ],
        prompt=PROMPT_6553_C2,
        expect_ready=False,
        calls=2,
        checks=_c(
            Check("jql_section", "section", "Recherche Jira", 3, label="## Recherche Jira"),
            Check("jql_line", "contains", "JQL :", 2, label="JQL écrit"),
            Check("linked", "section", "Tickets liés demandés", 1, label="liés"),
            Check("mep", "contains", "1.24.12", 1, label="MEP 6005"),
            Check("no_cartaud", "absent", "CARTAUD", 3, label="pas CARTAUD 6271"),
            Check("no_omitted_ocr", "absent", "16 additional items omitted", 1, label="pas dump OCR lié"),
            Check("screen", "contains", "PlanificationBonsTravauxController", 2, label="écran Travaux"),
            Check("salarie", "contains", "salarieId", 2, label=":salarieId"),
            Check("not_planif", "contains", "ce n'est pas l'id de planification", 2, label="UUID pas planif"),
            Check("confluence", "section", "Confluence", 1, label="## Confluence"),
            Check("trous", "trous_non_vide", "", 3, label="Trous non vide"),
            Check("ready_false", "ready", "false", 2, label="pas ready si trous"),
            Check(
                "order",
                "heading_order",
                "Mission|Ticket|Tickets liés demandés|Recherche Jira|Code|Confluence|Trous|À l'orchestrateur",
                2,
                label="ordre des sections",
            ),
            Check("sql_next", "regex", r"SQL|grep|rejeu", 1, label="orchestrateur SQL/grep"),
        ),
    ),
}

DEFAULT_CASE_IDS = [
    "LYSI-6160",
    "LYSI-6417-pdf",
    "LYSI-6417-dir",
    "LYSI-6553-c1",
    "LYSI-6553-c2",
]


def score_to_dict(score: Score) -> dict:
    return {
        "case": score.case_id,
        "passed": score.passed,
        "total": score.total,
        "pct": score.pct,
        "ok": score.ok,
        "ready": score.ready,
        "notes": score.notes,
        "skipped": score.skipped,
        "hits": [
            {
                "id": item.id,
                "label": item.label,
                "ok": item.ok,
                "weight": item.weight,
                "detail": item.detail,
            }
            for item in score.hits
        ],
    }


def render_score(score: Score) -> str:
    lines = [
        f"## {score.case_id} — {score.passed}/{score.total} ({score.pct} %)",
        "",
        "| Contrôle | Résultat | Détail |",
        "| --- | --- | --- |",
    ]
    for item in score.hits:
        mark = "OK" if item.ok else "KO"
        lines.append(f"| {item.label} | {mark} | {item.detail} |")
    if score.notes:
        lines.append("")
        lines.extend(f"- {note}" for note in score.notes)
    return "\n".join(lines)
