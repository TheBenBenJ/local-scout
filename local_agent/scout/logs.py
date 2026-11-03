"""Deterministic extraction of failures from a log or a CI trace. Never the whole raw text.

Same principle as pdf.py for Annots: keep only the useful objects (here, the signal lines
and their nearby context), not the document just in case.
"""

from __future__ import annotations

import re

_SIGNAL = re.compile(
    r"""
    ^\s*\d+\)\s+\S+::\S+ |                       # PHPUnit "1) TestClass::testMethod"
    \bFAILURES!\b | \bERRORS!\b |                # PHPUnit / paratest summary
    ^\s*FAIL(?:ED)?\b |                          # pytest / jest / go test
    \bFatal\ error\b | \bUncaught\ [A-Z]\w*Exception\b |
    \bException\b | \bAssertionError\b |
    Traceback\ \(most\ recent\ call\ last\) |
    ^\s*File\ "[^"]+",\ line\ \d+ |              # pytest traceback frame
    \bpanic:\s | \bSegmentation\ fault\b |
    \bnpm\ ERR!\b | error\s+TS\d+ |               # npm / tsc
    \#\#\[error\] | \bERROR\b | \bCRITICAL\b      # GitHub Actions / generic
    """,
    re.IGNORECASE | re.VERBOSE,
)

_CONTEXT_BEFORE = 2
_CONTEXT_AFTER = 6
_TAIL_FALLBACK_LINES = 40
DEFAULT_MAX_CHARS = 6000


def extract_failures(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    """Keep failure/error lines and their nearby context, de-duplicate repetitive noise.

    Without a signal (clean build, green suite), return the bounded tail rather than the raw text: the
    outcome of a run is usually at the end, and an absence of signal is still data, not a summary.
    """
    lines = (text or "").splitlines()
    total_lines = len(lines)
    total_bytes = len(text or "")
    if not lines:
        return {
            "kept": "",
            "total_lines": 0,
            "kept_lines": 0,
            "total_bytes": total_bytes,
            "kept_bytes": 0,
            "match_count": 0,
            "truncated": False,
        }

    keep = [False] * total_lines
    match_count = 0
    for index, line in enumerate(lines):
        if _SIGNAL.search(line):
            match_count += 1
            start = max(0, index - _CONTEXT_BEFORE)
            end = min(total_lines, index + _CONTEXT_AFTER + 1)
            for i in range(start, end):
                keep[i] = True

    if match_count == 0:
        tail = lines[-_TAIL_FALLBACK_LINES:]
        kept_text = _dedupe("\n".join(tail))
        truncated = len(kept_text) > max_chars or total_lines > _TAIL_FALLBACK_LINES
        if len(kept_text) > max_chars:
            kept_text = kept_text[:max_chars].rstrip() + "\n[truncated]"
        return {
            "kept": kept_text,
            "total_lines": total_lines,
            "kept_lines": min(_TAIL_FALLBACK_LINES, total_lines),
            "total_bytes": total_bytes,
            "kept_bytes": len(kept_text),
            "match_count": 0,
            "truncated": truncated,
        }

    kept_lines_list = [line for line, flag in zip(lines, keep) if flag]
    kept_text = _dedupe("\n".join(kept_lines_list))
    truncated = len(kept_text) > max_chars
    if truncated:
        kept_text = kept_text[:max_chars].rstrip() + "\n[truncated]"
    return {
        "kept": kept_text,
        "total_lines": total_lines,
        "kept_lines": sum(keep),
        "total_bytes": total_bytes,
        "kept_bytes": len(kept_text),
        "match_count": match_count,
        "truncated": truncated,
    }


def _dedupe(text: str) -> str:
    """Collapse runs of 3+ identical lines (progress bars, repeated dots)."""
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    total = len(lines)
    while index < total:
        line = lines[index]
        end = index + 1
        while end < total and lines[end] == line:
            end += 1
        run = end - index
        out.append(line)
        if run > 2:
            out.append(f"[ligne répétée {run - 1} fois de plus]")
        elif run == 2:
            out.append(line)
        index = end
    return "\n".join(out)
