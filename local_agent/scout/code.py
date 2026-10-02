"""Extraits rg : chemins fidèles, fenêtres autour des symboles, pas le début de classe."""

from __future__ import annotations

import re
from pathlib import Path

from .. import files
from ..config import Config
from .dossier import Dossier

CODE_GLOBS = ["*.php", "*.yml", "*.yaml", "*.xml", "*.twig", "!**/vendor/**"]

REVIEW_PATTERNS = [
    r"MessageHandler",
    r"createAndSubmit",
    r"findValidees",
    r"flush\s*\(",
    r"submit\s*\(",
    r"UniqueEntity",
    r"UniqueConstraint",
    r"#\[Unique",
    r"\bcontinue\b",
]

_NOISE_PREFIX = ("use ", "namespace ", "declare(", "declare ")
_PROPERTY = re.compile(
    r"^\s*(?:private|protected|public)\s+(?:readonly\s+)?(?:\??[\w\\]+\s+)?\$"
)
_CONSTRUCT = re.compile(r"function\s+__construct\b")


def is_noise(text: str) -> bool:
    stripped = (text or "").lstrip()
    if stripped.startswith(_NOISE_PREFIX):
        return True
    if _CONSTRUCT.search(stripped):
        return True
    if stripped.startswith(("/**", "*", "//")):
        return True
    if _PROPERTY.match(stripped):
        return True
    return False


def next_excerpt_id(dossier: Dossier) -> str:
    dossier.excerpt_seq += 1
    return f"e{dossier.excerpt_seq}"


def line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def basename_candidates(config: Config, name: str, *, limit: int = 8) -> list[str]:
    if not name or "/" in name:
        return []
    unlocked = files.unlocked_directories(config, config.repo_root)
    args = ["--files", "--no-messages", "--glob", f"**/{name}"]
    try:
        lines = files._run_ripgrep(args, config.repo_root, timeout=30)
    except Exception:
        return []
    found: list[str] = []
    for line in lines:
        relative = line.replace("\\", "/").lstrip("./")
        if files.is_denied(relative, unlocked=unlocked):
            continue
        if Path(relative).name != name:
            continue
        found.append(relative)
        if len(found) >= limit:
            break
    return found


def review_roots(named_files: list[str]) -> list[str]:
    roots: list[str] = []
    for item in named_files:
        parts = Path(item).parts
        if len(parts) >= 2 and parts[0] == "lib":
            root = str(Path(*parts[:2]))
        elif parts:
            root = parts[0]
        else:
            continue
        if root not in roots:
            roots.append(root)
    return roots


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    ordered = sorted(spans)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 4:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def windows_for(matches: list[dict], total_lines: int, *, max_spans: int = 3, max_lines: int = 15) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in matches:
        line = int(match.get("line") or 0)
        if line < 1:
            continue
        text = str(match.get("text") or "")
        if _CONSTRUCT.search(text):
            continue
        decl = bool(re.search(r"\bfunction\b|\bclass\b|\brouting\b|->render\(", text))
        start = max(1, line - (1 if decl else 2))
        end = min(total_lines, start + max_lines - 1)
        spans.append((start, end))
        if len(spans) >= max_spans * 2:
            break
    return _merge_spans(spans)[:max_spans]


def read_windows(path: Path, spans: list[tuple[int, int]], *, cap: int = 2200) -> tuple[str, int]:
    if not spans:
        return "", 0
    wanted: set[int] = set()
    for start, end in spans:
        for index in range(start, end + 1):
            wanted.add(index)
    contents: dict[int, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle, start=1):
            if index in wanted:
                contents[index] = line.rstrip()
    parts: list[str] = []
    prev: int | None = None
    for index in sorted(contents):
        if prev is not None and index > prev + 1:
            parts.append("…")
        parts.append(f"{index}| {contents[index]}")
        prev = index
    text = "\n".join(parts)
    if len(text) > cap:
        text = text[:cap].rstrip() + "\n…"
    return text, len(contents)


def _mark_truncated(
    dossier: Dossier,
    relative: str,
    *,
    kept_lines: int,
    total_lines: int,
    kept_bytes: int,
    total_bytes: int,
    excerpt_id: str,
    listed: bool,
) -> None:
    if kept_lines >= total_lines and kept_bytes >= total_bytes:
        return
    dossier.sample_based = True
    if not listed:
        return
    for item in dossier.truncated_sources:
        if item.get("path") == relative:
            ids = list(item.get("ids") or [])
            if excerpt_id not in ids:
                ids.append(excerpt_id)
            item["ids"] = ids
            item["kept_lines"] = max(int(item.get("kept_lines") or 0), kept_lines)
            return
    dossier.truncated_sources.append(
        {
            "path": relative,
            "kept_lines": kept_lines,
            "total_lines": total_lines,
            "kept_bytes": kept_bytes,
            "total_bytes": total_bytes,
            "ids": [excerpt_id],
        }
    )


def _push_excerpt(
    dossier: Dossier,
    relative: str,
    excerpt: str,
    spans: list[tuple[int, int]],
    *,
    total_lines: int,
    total_bytes: int,
    listed: bool,
    symbol: str = "",
) -> None:
    excerpt_id = next_excerpt_id(dossier)
    kept_lines = excerpt.count("\n") + (1 if excerpt else 0)
    location = relative
    if spans:
        location = f"{relative}:{spans[0][0]}-{spans[-1][1]}"
    truncated = kept_lines < total_lines
    dossier.code.append(
        {
            "file": relative,
            "location": location,
            "text": excerpt,
            "id": excerpt_id,
            "symbol": symbol,
            "truncated": truncated,
            "kept_lines": kept_lines,
            "total_lines": total_lines,
            "kept_bytes": len(excerpt.encode("utf-8")),
            "total_bytes": total_bytes,
        }
    )
    dossier.ledger.add_text("code", excerpt)
    _mark_truncated(
        dossier,
        relative,
        kept_lines=kept_lines,
        total_lines=total_lines,
        kept_bytes=len(excerpt.encode("utf-8")),
        total_bytes=total_bytes,
        excerpt_id=excerpt_id,
        listed=listed,
    )


def add_file_from_matches(
    config: Config,
    dossier: Dossier,
    relative: str,
    matches: list[dict],
    *,
    listed: bool = False,
    symbol: str = "",
) -> None:
    if any(item.get("file") == relative for item in dossier.code):
        return
    path = config.repo_root / relative
    if not path.is_file():
        return
    total_lines = line_count(path)
    try:
        total_bytes = path.stat().st_size
    except OSError:
        dossier.holes.append(f"{relative}: source demandée illisible")
        return
    useful = [match for match in matches if not is_noise(str(match.get("text") or ""))]
    spans = windows_for(useful or matches, total_lines)
    excerpt, _kept = read_windows(path, spans)
    if not excerpt:
        excerpt = f"(aucun extrait prioritaire, {total_lines} lignes — Relire {relative}:1)"
        spans = []
    _push_excerpt(
        dossier,
        relative,
        excerpt,
        spans,
        total_lines=total_lines,
        total_bytes=total_bytes,
        listed=listed,
        symbol=symbol,
    )


def load_named_file(
    config: Config,
    dossier: Dossier,
    relative: str,
    symbols: list[str],
    *,
    review: bool = False,
    listed: bool = True,
) -> None:
    relative = (relative or "").strip().lstrip("/")
    if not relative:
        return
    path = config.repo_root / relative
    if path.is_file():
        _excerpt_named(config, dossier, relative, symbols, review=review, listed=listed)
        return
    name = Path(relative).name
    candidates = basename_candidates(config, name)
    if candidates:
        labeled = ", ".join(
            f"{item} ({line_count(config.repo_root / item)} lignes)" for item in candidates
        )
        dossier.locations.append(f"non trouvé à {relative}, candidats : {labeled}")
        dossier.absence_guard = True
        for item in candidates[:3]:
            _excerpt_named(config, dossier, item, symbols, review=review, listed=listed)
        return
    dossier.holes.append(
        f"non trouvé à {relative} (chemin exact et basename {name} : 0 match)"
    )
    dossier.absence_guard = True


def _excerpt_named(
    config: Config,
    dossier: Dossier,
    relative: str,
    symbols: list[str],
    *,
    review: bool,
    listed: bool,
) -> None:
    if any(item.get("file") == relative for item in dossier.code):
        return
    path = config.repo_root / relative
    patterns = [re.escape(symbol) for symbol in symbols if symbol]
    if review or not patterns:
        patterns = list(dict.fromkeys(patterns + REVIEW_PATTERNS))
    if relative.endswith((".yml", ".yaml")):
        patterns = list(dict.fromkeys(patterns + [r"routing", r"MessageHandler", r"Message"]))
    if not patterns:
        patterns = [r"\bfunction\b"]
    try:
        matches, total = files.grep(
            config,
            path,
            patterns,
            max_matches=24,
            ignore_case=False,
            max_count_per_file=24,
            balance_by_file=False,
        )
    except Exception as error:  # noqa: BLE001
        dossier.errors.append(f"{relative}: {error}")
        dossier.holes.append(f"{relative}: source demandée illisible")
        return
    dossier.rg_counts[relative] = total
    if total > len(matches):
        dossier.sample_based = True
    add_file_from_matches(config, dossier, relative, matches, listed=listed)


def review_rank(relative: str) -> int:
    name = Path(relative).name
    score = 0
    if "Handler" in name:
        score += 50
    if name.endswith("Controller.php"):
        score += 25
    if relative.endswith(".twig"):
        score += 35
    if "messenger.y" in relative.replace("\\", "/"):
        score += 40
    if name.endswith("Test.php"):
        score += 25
    if "Repository" in name:
        score += 15
    if "/Entity/" in relative.replace("\\", "/") or relative.endswith("Entity.php"):
        score -= 15
    return score


def screen_rank(relative: str, texts: list[str]) -> int:
    blob = "\n".join(texts)
    score = review_rank(relative)
    if "->render(" in blob or "render(" in blob:
        score += 50
    if relative.endswith(".twig"):
        score += 20
    if re.search(r"^\s*use\s+", blob, re.M) and "Controller" in relative and "->render(" not in blob:
        score -= 80
    return score


def screen_pass(
    config: Config,
    dossier: Dossier,
    needles: list[str],
    seen: set[str],
) -> None:
    patterns = [re.escape(item) for item in needles if item]
    if not patterns:
        return
    patterns = list(dict.fromkeys(patterns))[:12]
    try:
        matches, total = files.grep(
            config,
            config.repo_root,
            patterns,
            globs=CODE_GLOBS,
            max_matches=40,
            ignore_case=False,
            max_count_per_file=6,
            balance_by_file=True,
        )
    except Exception as error:  # noqa: BLE001
        dossier.errors.append(f"rg écran : {error}")
        return
    if total > len(matches):
        dossier.sample_based = True
    grouped: dict[str, list[dict]] = {}
    for match in matches:
        relative = str(match.get("file") or "")
        if not relative or relative in seen:
            continue
        grouped.setdefault(relative, []).append(match)
    ranked = sorted(
        grouped.items(),
        key=lambda item: screen_rank(item[0], [str(row.get("text") or "") for row in item[1]]),
        reverse=True,
    )
    kept = 0
    for relative, group in ranked:
        if "Controller" in Path(relative).name:
            group = group + _render_matches(config, relative)
        blob = "\n".join(str(row.get("text") or "") for row in group)
        incidental = "Controller" in Path(relative).name and "render(" not in blob
        if incidental:
            dossier.incidental.append(f"`{relative}` : mention incidente, écarté")
            continue
        add_file_from_matches(config, dossier, relative, group)
        seen.add(relative)
        kept += 1
        if kept >= 3:
            break


def _render_matches(config: Config, relative: str, *, limit: int = 3) -> list[dict]:
    """Un contrôleur trouvé par un motif du ticket : ses render() disent quel écran il sert."""
    try:
        lines = (config.repo_root / relative).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found = []
    for number, text in enumerate(lines, start=1):
        if "->render(" in text:
            found.append({"file": relative, "line": number, "text": text})
            if len(found) >= limit:
                break
    return found


def review_pass(
    config: Config,
    dossier: Dossier,
    named_files: list[str],
    symbols: list[str],
    seen: set[str],
) -> None:
    roots = review_roots(named_files) or [""]
    patterns = list(REVIEW_PATTERNS)
    patterns.extend(re.escape(symbol) for symbol in symbols[:8] if symbol)
    for root in roots:
        target = config.repo_root / root if root else config.repo_root
        if not target.exists():
            continue
        try:
            matches, total = files.grep(
                config,
                target,
                patterns,
                globs=CODE_GLOBS,
                max_matches=30,
                ignore_case=False,
                max_count_per_file=5,
                balance_by_file=True,
            )
        except Exception as error:  # noqa: BLE001
            dossier.errors.append(f"rg review {root or '.'}: {error}")
            continue
        if total > len(matches):
            dossier.sample_based = True
        grouped: dict[str, list[dict]] = {}
        for match in matches:
            relative = str(match.get("file") or "")
            if not relative or relative in seen:
                continue
            grouped.setdefault(relative, []).append(match)
        ranked = sorted(grouped.items(), key=lambda item: review_rank(item[0]), reverse=True)
        for relative, group in ranked[:8]:
            add_file_from_matches(config, dossier, relative, group)
            seen.add(relative)

    for yaml_name in ("config/packages/messenger.yaml", "config/packages/messenger.yml"):
        if yaml_name in seen:
            continue
        if (config.repo_root / yaml_name).is_file():
            load_named_file(config, dossier, yaml_name, symbols, review=True, listed=True)
            seen.add(yaml_name)

    for relative in list(seen):
        stem = Path(relative).stem
        if not stem or stem.endswith("Test"):
            continue
        for candidate in basename_candidates(config, f"{stem}Test.php")[:2]:
            if candidate in seen:
                continue
            load_named_file(config, dossier, candidate, symbols, review=True, listed=False)
            seen.add(candidate)
