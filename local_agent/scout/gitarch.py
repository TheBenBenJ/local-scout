"""Archéologie de branche : quelles branches portent un motif, et leur statut de fusion.

Ramassage seulement : `git log --grep`, `git branch --contains`, `git merge-base --is-ancestor`.
Pas d'interprétation de « laquelle est la bonne » — l'orchestrateur tranche.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_MAIN_CANDIDATES = ("main", "master", "develop", "dev", "trunk")
_MAX_BRANCHES = 20
_MAX_GREP_COMMITS = 30


def _run(args: list[str], cwd: Path, *, timeout: int = 15) -> tuple[int, str]:
    try:
        process = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    return process.returncode, (process.stdout or process.stderr or "").strip()


def _short_name(ref: str) -> str:
    ref = ref.strip()
    if ref.endswith("/HEAD"):
        return ""
    if ref.startswith("origin/"):
        return ref.split("/", 1)[-1]
    return ref


def _branch_names(repo_root: Path) -> list[str]:
    code, out = _run(["branch", "-a", "--format=%(refname:short)"], repo_root)
    if code != 0:
        return []
    names = {_short_name(line) for line in out.splitlines() if line.strip()}
    names.discard("")
    return sorted(names)


def _main_branches(repo_root: Path) -> list[str]:
    present = set(_branch_names(repo_root))
    return [name for name in _MAIN_CANDIDATES if name in present]


def find_branches(pattern: str, repo_root: Path) -> dict:
    """Branches dont le nom ou l'historique porte `pattern`, avec leur statut de fusion vers les
    branches principales détectées (main/master/develop/dev/trunk, celles qui existent ici)."""
    pattern = (pattern or "").strip()
    if not pattern:
        return {"pattern": pattern, "branches": [], "main_branches": [], "commit_matches": 0, "error": "motif vide"}
    repo_root = Path(repo_root)
    if not (repo_root / ".git").exists():
        return {
            "pattern": pattern,
            "branches": [],
            "main_branches": [],
            "commit_matches": 0,
            "error": "pas un dépôt git (pas de .git à la racine)",
        }

    by_name = {name for name in _branch_names(repo_root) if pattern.lower() in name.lower()}

    code, out = _run(["log", "--all", f"--grep={pattern}", "-i", "--format=%H"], repo_root)
    commit_shas = [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []

    by_history: set[str] = set()
    for sha in commit_shas[:_MAX_GREP_COMMITS]:
        code, out = _run(["branch", "-a", "--contains", sha, "--format=%(refname:short)"], repo_root)
        if code != 0:
            continue
        for line in out.splitlines():
            name = _short_name(line)
            if name:
                by_history.add(name)

    candidates = sorted(by_name | by_history)[:_MAX_BRANCHES]
    mains = _main_branches(repo_root)
    branches = []
    for name in candidates:
        merged_into = []
        for main in mains:
            if main == name:
                continue
            code, _out = _run(["merge-base", "--is-ancestor", name, main], repo_root)
            if code == 0:
                merged_into.append(main)
        code, tip = _run(["log", "-1", "--format=%h %ad %an", "--date=short", name], repo_root)
        branches.append(
            {
                "branch": name,
                "matched_name": name in by_name,
                "matched_history": name in by_history,
                "merged_into": merged_into,
                "tip": tip if code == 0 else "",
            }
        )
    return {
        "pattern": pattern,
        "main_branches": mains,
        "commit_matches": len(commit_shas),
        "branches": branches,
        "error": None,
    }
