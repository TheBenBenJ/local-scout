"""Jira adapter. Credentials come from the environment or the repo's .claude/.env.local."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from . import atlassian


def _adf_text(node: object) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for part in (_adf_text(item) for item in node) if part)
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    chunks = [_adf_text(child) for child in (node.get("content") or [])]
    text = "\n".join(chunk for chunk in chunks if chunk)
    if node.get("type") in {"paragraph", "heading", "blockquote", "listItem"}:
        return text.strip() + "\n"
    return text

_MAX_TEXT = 12000
_MAX_COMMENTS = 12


def _comments(node: object) -> list[dict]:
    """The exchange with the reporter lives in the comments, not in the description."""
    items = (node or {}).get("comments") if isinstance(node, dict) else None
    packed = []
    for item in (items or [])[-_MAX_COMMENTS:]:
        body = _adf_text(item.get("body")).strip()
        if not body:
            continue
        packed.append({
            "author": ((item.get("author") or {}).get("displayName") or ""),
            "created": str(item.get("created") or "")[:10],
            "body": body[:2000],
        })
    return packed


def fetch(key: str, repo_root: Path | None = None, *, attachments: bool = True) -> dict:
    """Return an ISSUE CONTRACT. If Jira is not configured, explain how to add it."""
    creds = atlassian.credentials(repo_root)
    if not creds["base"] or not creds["token"]:
        return {
            "configured": False,
            "error": (
                "Jira is not configured. Put JIRA_URL, JIRA_USERNAME and JIRA_API_TOKEN in "
                "the target repo's .claude/.env.local (lysi skills already use these names), "
                "or JIRA_BASE_URL / JIRA_TOKEN / JIRA_EMAIL in the environment. "
                "No secret is stored in local-agent."
            ),
            "key": key,
        }
    wanted = "summary,description,status,issuetype,components,attachment,comment,fixVersions"
    url = f"{creds['base']}/rest/api/3/issue/{key}?fields={wanted}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    atlassian.authorize(request, creds)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            issue = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as error:
        return {"configured": True, "error": f"Jira HTTP {error.code} for {key}", "key": key, "base": creds["base"]}
    except urllib.error.URLError as error:
        return {"configured": True, "error": f"Jira request failed: {error.reason}", "key": key, "base": creds["base"]}
    fields = issue.get("fields") or {}
    description = fields.get("description")
    if isinstance(description, dict):
        description = _adf_text(description)
    raw_attachments = fields.get("attachment") or []
    names = [str(item.get("filename") or "") for item in raw_attachments if item.get("filename")]
    return {
        "configured": True,
        "key": key,
        "goal": fields.get("summary") or "",
        "acceptance_criteria_verbatim": str(description or "").strip()[:_MAX_TEXT],
        "comments": _comments(fields.get("comment")),
        "status": (fields.get("status") or {}).get("name"),
        "issuetype": (fields.get("issuetype") or {}).get("name"),
        "components": [item.get("name") for item in (fields.get("components") or []) if item.get("name")],
        "fix_versions": [
            str(item.get("name") or "")
            for item in (fields.get("fixVersions") or [])
            if item.get("name")
        ],
        "open_questions": [],
        "attachments": names[:20] if attachments else [],
        "attachment_files": (
            [
                {
                    "filename": str(item.get("filename") or ""),
                    "mime": str(item.get("mimeType") or ""),
                    "content": str(item.get("content") or ""),
                }
                for item in raw_attachments
                if item.get("filename") and item.get("content")
            ][:20]
            if attachments
            else []
        ),
    }


def search(jql: str, repo_root: Path | None = None, *, limit: int = 5) -> dict:
    """JQL borné. Ne dump pas les issues : key, summary, status, type, 5 lignes."""
    query = (jql or "").strip()
    creds = atlassian.credentials(repo_root)
    empty = {"configured": bool(creds["base"] and creds["token"]), "jql": query, "total": 0, "results": []}
    if not query:
        empty["error"] = "JQL vide"
        return empty
    if not creds["base"] or not creds["token"]:
        empty["error"] = "Jira is not configured"
        empty["configured"] = False
        return empty
    fields = ["summary", "status", "issuetype", "description", "fixVersions"]
    payload = None
    last_error = ""
    body = json.dumps({"jql": query, "maxResults": limit, "fields": fields}).encode("utf-8")
    for path in ("/rest/api/3/search/jql", "/rest/api/3/search"):
        request = urllib.request.Request(
            f"{creds['base']}{path}",
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        atlassian.authorize(request, creds)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            break
        except urllib.error.HTTPError as error:
            last_error = f"Jira HTTP {error.code} for search"
            if error.code not in {400, 404, 410}:
                empty["error"] = last_error
                return empty
        except urllib.error.URLError as error:
            empty["error"] = f"Jira request failed: {error.reason}"
            return empty
    if payload is None:
        empty["error"] = last_error or "Jira search failed"
        return empty
    issues = payload.get("issues") or payload.get("results") or []
    packed = []
    for item in issues[:limit]:
        fields_node = item.get("fields") or {}
        description = fields_node.get("description")
        if isinstance(description, dict):
            description = _adf_text(description)
        packed.append(
            {
                "key": item.get("key") or "",
                "goal": fields_node.get("summary") or "",
                "status": (fields_node.get("status") or {}).get("name") or "",
                "issuetype": (fields_node.get("issuetype") or {}).get("name") or "",
                "fix_versions": [
                    str(ver.get("name") or "")
                    for ver in (fields_node.get("fixVersions") or [])
                    if ver.get("name")
                ],
                "excerpt": str(description or "").strip()[:400],
            }
        )
    return {
        "configured": True,
        "jql": query,
        "total": int(payload.get("total") or len(issues)),
        "results": packed,
    }


_IMAGE_SUFFIX = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def save_images(packed: dict, dest: Path, repo_root: Path | None = None, *, limit: int = 8) -> list[Path]:
    """Écrit les PNG déjà décrits par fetch(). Pas de second GET ticket."""
    if packed.get("error"):
        return []
    creds = atlassian.credentials(repo_root)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for item in packed.get("attachment_files") or []:
        name = str(item.get("filename") or "")
        url = str(item.get("content") or "")
        if not name or not url:
            continue
        if Path(name).suffix.lower() not in _IMAGE_SUFFIX:
            continue
        target = dest / Path(name).name
        request = urllib.request.Request(url)
        atlassian.authorize(request, creds)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                target.write_bytes(response.read())
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            continue
        if target.is_file() and target.stat().st_size > 0:
            saved.append(target)
        if len(saved) >= limit:
            break
    return saved


def download_images(key: str, dest: Path, repo_root: Path | None = None, *, limit: int = 8) -> list[Path]:
    """Télécharge les pièces image d'un ticket. Chemins absolus pour l'OCR."""
    return save_images(fetch(key, repo_root), dest, repo_root, limit=limit)
