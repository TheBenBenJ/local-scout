"""Extraction déterministe de clés depuis une mission ou un corps de ticket. Pas de LLM."""

from __future__ import annotations

import re

from pathlib import Path

from ..router import explicit_symbols

LYSI_KEY = re.compile(r"\bLYSI-\d+\b", re.IGNORECASE)
CONFLUENCE_URI = re.compile(r"confluence://(\d+)")
CONFLUENCE_PAGE = re.compile(
    r"(?:atlassian\.net)?/wiki/spaces/[^/\s]+/pages/(\d{6,})",
    re.IGNORECASE,
)
CONFLUENCE_PAGES = re.compile(r"/pages/(\d{6,})", re.IGNORECASE)
IMAGE_NAME = re.compile(r"\b(image-\d{8}-\d{6}\.(?:png|jpg|jpeg|webp))\b", re.IGNORECASE)
# Ne pas ancrer sur \b avant src/ : ça réécrit lib/bundle/src/Foo.php en src/Foo.php.
REPO_FILE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:lib|src|tests|assets|config|app)(?:/[A-Za-z0-9_.-]+)+\.(?:php|ts|twig|yml|yaml|xml))"
)
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
CAMEL_IDENT = re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]{3,}\b")
_REVIEW = re.compile(
    r"\b(revue|review|code review|pull request|\bPR\b|merge request)\b",
    re.IGNORECASE,
)
_OCR_NEED = re.compile(
    r"\b(tableau|écran|ecran|tampon|screenshot|capture|ocr|"
    r"image-\d{8}-\d{6}|interface utilisateur)\b",
    re.IGNORECASE,
)
_ANNOT_NEED = re.compile(
    r"\b(annot|surlign|highlight|commentaire jaune|commentaires jaunes|"
    r"post-it|sticky note|quadpoints|free.?text|strikeout)\b",
    re.IGNORECASE,
)
_PDF_TEXT_NEED = re.compile(
    r"\b(pdftotext|texte de page|plein texte|full.?text)\b",
    re.IGNORECASE,
)
_HANDWRITE_NEED = re.compile(
    r"\b(manuscrit|note manuscrite|tampon image|handwrit)\b",
    re.IGNORECASE,
)
_GREP_NEED = re.compile(r"\b(grep|ripgrep|\brg\b|où est|where is)\b", re.IGNORECASE)
_JIRA_SEARCH = re.compile(
    r"\b(doublons?|tickets? existants?|jql)\b|"
    r"\b(?:chercher|rechercher|search)\b[^.\n]{0,60}\b(?:tickets?|jira|doublons?)\b",
    re.IGNORECASE,
)
_EXTRACTION = re.compile(
    r"^\W*(?:LYSI-\d+\s*:?\s*)?(?:extraire|recenser|lister|relever|lire|récupérer|recuperer|contexte de)\b",
    re.IGNORECASE,
)
_SCREEN_NEED = re.compile(r"\b(écran|ecran|contrôleur|controleur|controller|render|template|twig)\b", re.IGNORECASE)
_CONFLUENCE_NEED = re.compile(r"\b(confluence|documentation|page du domaine|règle métier|regle metier)\b", re.IGNORECASE)
_COMMENT_NEED = re.compile(r"\b(commentaires?|échanges?|echanges?|arbitrages?|décisions?|decisions?|réponses?)\b", re.IGNORECASE)
_URL_UUID = re.compile(
    r"/([A-Za-z0-9_-]{3,})/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_ROUTE_PARAM = re.compile(r"/\{(\w+)\}")
_JQL_STOP = {
    "fetch", "chercher", "search", "ticket", "existant", "existants", "même", "meme",
    "défaut", "defaut", "doublon", "jql", "lysi", "sans", "avec", "pour", "dans",
    "les", "des", "une", "sur", "plus", "résultats", "resultats", "conclure",
    "absence", "mission", "sources", "commentaires", "jaunes",
    "extraire", "recenser", "lister", "relever", "lire", "récupérer", "recuperer",
    "issuetype", "exact", "exacte", "titre", "statut", "priorité", "priorite",
    "constat", "attendu", "utiles", "liens", "pièces", "pieces", "jointes", "champs",
    "analyse", "contexte", "diagnostiquer", "diagnostic", "rassembler", "captures",
    "capture", "description", "texte", "libre", "clés", "cles", "citées", "citees",
    "personnalisés", "personnalises", "devra", "décider", "decider", "cause",
}
_TICKET_HEAD = re.compile(
    r"(?im)^(?:#{1,6}\s*|[*+-]\s*)?"
    r"(user\s*story|histoire\s+utilisateur|en tant que|"
    r"d[ée]cisions?|decisions?|"
    r"crit[eè]res?\s+d['’ ]?acceptation|acceptance\s+criteria|"
    r"\bac\b)\b"
)
_CODE_SUFFIX = {".php", ".ts", ".twig", ".yml", ".yaml", ".xml"}
_IMAGE_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_PDF_SUFFIX = {".pdf"}
_SOURCE_SUFFIX = _CODE_SUFFIX | _IMAGE_SUFFIX | _PDF_SUFFIX
_CLASS_SUFFIXES = (
    "Service", "Helper", "Factory", "Manager", "Handler", "Connector",
    "Repository", "Entity", "Message", "Command", "Controller",
    "Subscriber", "Provider", "Adapter",
)

_NOISE_SYMBOLS = {
    "LYSI", "Jira", "Confluence", "SILAE", "HTTP", "JSON", "UUID",
    "Bonjour", "Merci", "Attendu", "Problème", "Correction",
    "Exemple", "Exemples", "Commentaire", "Conclusion",
}


def _uniq(items: list[str], *, limit: int) -> list[str]:
    seen: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def ticket_keys(text: str, *, primary: str | None = None, limit: int = 6) -> list[str]:
    found = [match.group(0).upper() for match in LYSI_KEY.finditer(text or "")]
    normalized = []
    for key in found:
        if key not in normalized:
            normalized.append(key)
    if primary:
        head = primary.strip().upper()
        if not head.startswith("LYSI-"):
            head = f"LYSI-{head}" if head.isdigit() else head
        rest = [item for item in normalized if item != head]
        return _uniq([head] + rest, limit=limit)
    return _uniq(normalized, limit=limit)


def confluence_ids(text: str, *, limit: int = 3) -> list[str]:
    found: list[str] = []
    for pattern in (CONFLUENCE_URI, CONFLUENCE_PAGE, CONFLUENCE_PAGES):
        for match in pattern.finditer(text or ""):
            found.append(match.group(1))
    return _uniq(found, limit=limit)


def image_names(text: str, *, limit: int = 8) -> list[str]:
    return _uniq([match.group(1) for match in IMAGE_NAME.finditer(text or "")], limit=limit)


def prefer_full_paths(items: list[str]) -> list[str]:
    """Garde lib/bundle/src/Foo.php et écarte le suffixe src/Foo.php."""
    found = [item.strip() for item in items if str(item or "").strip()]
    kept: list[str] = []
    for item in found:
        if any(other != item and other.endswith("/" + item) for other in found):
            continue
        if item not in kept:
            kept.append(item)
    return kept


def as_repo_path(uri: str) -> str | None:
    """Recopie un chemin repo-relative tel quel. Jamais de réécriture src/ depuis lib/…/src/."""
    raw = str(uri or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered.startswith(("jira://", "confluence://", "image://", "log://", "ci://", "git://")):
        return None
    if lowered.startswith("repo://"):
        raw = raw.split("://", 1)[-1]
    raw = raw.strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if Path(raw).suffix.lower() in _SOURCE_SUFFIX or "/" in raw:
        return raw
    return None


def source_paths(sources: list[str] | None, *, limit: int = 12) -> list[str]:
    found = []
    for item in sources or []:
        path = as_repo_path(item)
        if path:
            found.append(path)
    return _uniq(prefer_full_paths(found), limit=limit)


def repo_files(text: str, *, limit: int = 8) -> list[str]:
    found = [match.group(1) for match in REPO_FILE.finditer(text or "")]
    return _uniq(prefer_full_paths(found), limit=limit)


def is_review(text: str) -> bool:
    return bool(_REVIEW.search(text or ""))


def wants_ocr(mission: str, ticket_text: str = "") -> bool:
    blob = f"{mission or ''}\n{ticket_text or ''}"
    if image_names(blob):
        return True
    if wants_annots(mission):
        return False
    if is_review(mission) and not _OCR_NEED.search(blob):
        return False
    return bool(_OCR_NEED.search(blob))


def wants_annots(text: str) -> bool:
    return bool(_ANNOT_NEED.search(text or ""))


def wants_pdf_text(text: str) -> bool:
    return bool(_PDF_TEXT_NEED.search(text or ""))


def wants_handwriting(text: str) -> bool:
    return bool(_HANDWRITE_NEED.search(text or ""))


def is_grep_mission(text: str) -> bool:
    return bool(_GREP_NEED.search(text or ""))


def wants_jira_search(text: str) -> bool:
    return bool(_JIRA_SEARCH.search(text or ""))


def is_extraction(text: str) -> bool:
    """Mission de ramassage pur (« Extraire… », « Recenser… ») : pas d'écran ni de page exigés."""
    return bool(_EXTRACTION.search(text or ""))


def wants_screen(text: str) -> bool:
    return bool(_SCREEN_NEED.search(text or ""))


def wants_confluence(text: str) -> bool:
    return bool(_CONFLUENCE_NEED.search(text or ""))


def wants_comments(text: str) -> bool:
    return bool(_COMMENT_NEED.search(text or ""))


def url_slugs(text: str, *, limit: int = 4) -> list[str]:
    return _uniq([slug for slug, _value in url_uuid_hits(text)], limit=limit)


def is_ticket_diagnosis(mission: str, keys: list[str], listed: list[str]) -> bool:
    if wants_annots(mission) or is_review(mission):
        return False
    if any(is_pdf_path(item) for item in listed) and not keys:
        return False
    return bool(keys) or wants_jira_search(mission)


def jql_terms(text: str, *, limit: int = 6) -> list[str]:
    found: list[str] = []
    for token in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9']{3,}", text or ""):
        if token.lower() in _JQL_STOP or token.upper().startswith("LYSI"):
            continue
        if token.lower() not in {item.lower() for item in found}:
            found.append(token)
        if len(found) >= limit:
            break
    return found


def build_jql(mission: str, *, exclude: list[str] | None = None) -> str:
    terms = jql_terms(mission)
    if not terms:
        return ""
    clauses = " OR ".join(f'text ~ "{term}"' for term in terms[:6])
    jql = f"project = LYSI AND ({clauses})"
    keys = [key for key in (exclude or []) if key]
    if keys:
        jql += " AND key NOT IN (" + ", ".join(keys) + ")"
    return jql + " ORDER BY updated DESC"


def confluence_query(mission: str, ticket_text: str = "", goal: str = "") -> str:
    """Le titre du ticket décrit le domaine ; la mission décrit la consigne."""
    words = jql_terms(goal, limit=12)
    # Agence, nom de personne : en capitales dans les titres, sans valeur pour une recherche de domaine.
    plain = [word for word in words if not word.isupper()]
    terms = (plain if len(plain) >= 2 else words)[:4]
    if len(terms) < 2:
        terms = merge(terms, jql_terms(f"{mission}\n{ticket_text}", limit=4), limit=4)
    return " ".join(terms[:4])


def url_uuid_hits(text: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2).lower()) for match in _URL_UUID.finditer(text or "")]


def route_param_after(slug: str, text: str) -> str:
    if not slug:
        return ""
    match = re.search(rf"/{re.escape(slug)}/\{{(\w+)\}}", text or "")
    return match.group(1) if match else ""


def entity_for_route_param(param: str) -> tuple[str, str]:
    key = (param or "").lower()
    if key in {"salarieid", "salarie"}:
        return "salarie", "ce n'est pas l'id de planification"
    if key in {"planificationid", "planification"}:
        return "planification", ""
    if key in {"chantierid", "chantier"}:
        return "chantier", ""
    if key == "id":
        return "id (à recouper)", ""
    if param:
        return param, ""
    return "?", ""


def is_code_path(relative: str) -> bool:
    return Path(relative or "").suffix.lower() in _CODE_SUFFIX


def is_image_path(relative: str) -> bool:
    return Path(relative or "").suffix.lower() in _IMAGE_SUFFIX


def is_pdf_path(relative: str) -> bool:
    return Path(relative or "").suffix.lower() in _PDF_SUFFIX


def ticket_focus(text: str, *, limit: int = 2200) -> tuple[str, bool]:
    """User story + décisions + AC. Pas le ticket entier."""
    raw = (text or "").strip()
    if not raw:
        return "", False
    lines = raw.splitlines()
    starts = [index for index, line in enumerate(lines) if _TICKET_HEAD.search(line)]
    if not starts:
        truncated = len(raw) > limit
        return raw[:limit].rstrip(), truncated
    kept: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        kept.extend(lines[start:end])
        kept.append("")
    joined = "\n".join(kept).strip()
    truncated = len(joined) > limit or starts[0] > 0 or len(raw) > len(joined) + 40
    if len(joined) > limit:
        return joined[:limit].rstrip(), True
    return joined, truncated


def uuids(text: str, *, limit: int = 12) -> list[str]:
    return _uniq([match.group(0).lower() for match in UUID.finditer(text or "")], limit=limit)


def _useful(symbol: str) -> bool:
    if not symbol or symbol in _NOISE_SYMBOLS or symbol.upper().startswith("LYSI-"):
        return False
    if len(symbol) < 6:
        return False
    if symbol[0].islower() and any(ch.isupper() for ch in symbol[1:]):
        return True
    if symbol[0].isupper() and symbol.endswith(_CLASS_SUFFIXES):
        return True
    return False


def symbols(text: str, *, limit: int = 10) -> list[str]:
    found: list[str] = []
    for match in CAMEL_IDENT.findall(text or ""):
        if _useful(match) and match not in found:
            found.append(match)
    for item in explicit_symbols(text or ""):
        if _useful(item) and item not in found:
            found.append(item)
    methods = [item for item in found if item[0].islower()]
    classes = [item for item in found if item[0].isupper()]
    return _uniq(methods + classes, limit=limit)


def merge(head: list[str], tail: list[str], *, limit: int) -> list[str]:
    return _uniq(list(head) + list(tail), limit=limit)


def slug(mission: str, ticket: str | None) -> str:
    if ticket:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", ticket.strip())[:40].strip("-") or "mission"
    keys = ticket_keys(mission, limit=1)
    if keys:
        return keys[0]
    compact = re.sub(r"[^A-Za-z0-9]+", "-", (mission or "mission").strip())[:40].strip("-")
    return compact or "mission"
