"""GitLab adapter : trace de job CI seulement. Pas l'API pipeline complète, pas de diagnostic."""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .atlassian import env_roots

_FILES = (".claude/.env.local", ".env.local")
_KEYS = {
    "GITLAB_URL",
    "GITLAB_TOKEN",
    "GITLAB_PRIVATE_TOKEN",
    "GITLAB_PROJECT_ID",
    "GITLAB_PROJECT_PATH",
}
_MAX_TRACE_BYTES = 4_000_000


def _parse_env_file(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in _KEYS:
            continue
        found[key] = value.strip().strip("'\"")
    return found


def _file_values(repo_root: Path | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    for root in reversed(env_roots(repo_root)):
        for relative in _FILES:
            merged.update(_parse_env_file(root / relative))
    return merged


def _pick(values: dict[str, str], *names: str) -> str:
    for name in names:
        raw = (os.environ.get(name) or values.get(name) or "").strip()
        if raw:
            return raw
    return ""


def credentials(repo_root: Path | None = None) -> dict[str, str]:
    files = _file_values(repo_root)
    base = _pick(files, "GITLAB_URL").rstrip("/") or "https://gitlab.com"
    token = _pick(files, "GITLAB_TOKEN", "GITLAB_PRIVATE_TOKEN")
    project = _pick(files, "GITLAB_PROJECT_ID", "GITLAB_PROJECT_PATH")
    return {"base": base, "token": token, "project": project}


def fetch_trace(job_id: str, *, project: str = "", repo_root: Path | None = None) -> dict:
    """Télécharge la trace brute d'un job. Le filtrage (échecs/erreurs) est fait par scout/logs.py."""
    job_id = str(job_id or "").strip()
    if not job_id:
        return {"error": "job id manquant"}
    creds = credentials(repo_root)
    target_project = (project or creds["project"]).strip()
    if not target_project:
        return {
            "error": (
                "GitLab project not configured. Put GITLAB_URL, GITLAB_TOKEN and "
                "GITLAB_PROJECT_ID (or GITLAB_PROJECT_PATH) in the target repo's "
                ".claude/.env.local, or pass ci://gitlab/<project>/<job_id>."
            ),
            "job_id": job_id,
        }
    if not creds["token"]:
        return {
            "error": (
                "GitLab is not configured: GITLAB_TOKEN (or GITLAB_PRIVATE_TOKEN) missing. "
                "No secret is stored in local-scout."
            ),
            "job_id": job_id,
        }
    project_id = urllib.parse.quote(target_project, safe="")
    url = f"{creds['base']}/api/v4/projects/{project_id}/jobs/{job_id}/trace"
    request = urllib.request.Request(url, headers={"PRIVATE-TOKEN": creds["token"]})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(_MAX_TRACE_BYTES)
    except urllib.error.HTTPError as error:
        return {
            "error": f"GitLab HTTP {error.code} for job {job_id}",
            "job_id": job_id,
            "project": target_project,
            "base": creds["base"],
        }
    except urllib.error.URLError as error:
        return {
            "error": f"GitLab request failed: {error.reason}",
            "job_id": job_id,
            "project": target_project,
            "base": creds["base"],
        }
    return {
        "job_id": job_id,
        "project": target_project,
        "trace": raw.decode("utf-8", errors="replace"),
    }
