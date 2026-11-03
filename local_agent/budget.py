"""Frugality trade-off: only delegate what delegation actually lightens.

A synthesis produced by the model weighs 1,500 to 2,600 characters in practice. Below that
threshold, the raw evidence is both cheaper for the orchestrator and exact, whereas the synthesis
adds a risk of omission. Measurements in `tests/bench.py` and `tests/bench_exactitude.py`.
"""

from __future__ import annotations

from .report import Report

# Floor cost of a synthesis: below it, calling the model is an expense with no return.
PASSTHROUGH_CHARS = 2000

# A short enumeration must stay exhaustive: the model summarizes where it should list.
PASSTHROUGH_MATCHES = 60

# For a review or a synthesis, the deliverable is a comment, not the content: returning the raw text
# shifts the work to the orchestrator, which only pays off when the content is shorter than a synthesis.
PASSTHROUGH_CONTENT_CHARS = 1200

# A token never loaded is saved on every later prompt, not once. Measured on a long Claude recette
# session: 14,339 one-shot tokens → ~390,000 billed effect (~27×). 25 is that order of magnitude.


def is_worth_delegating(raw: str, threshold: int = PASSTHROUGH_CHARS) -> bool:
    return len(raw.strip()) > threshold


def billed_chars(saved_chars: int, remaining_turns: int) -> int:
    """One-shot avoided characters scaled by how many later prompts they would have stayed in."""
    turns = int(remaining_turns)
    if turns <= 0:
        return 0
    return max(0, int(saved_chars)) * turns


def tokens_from_chars(chars: int) -> int:
    return max(0, int(chars) // 4)


def savings_footer(
    source_chars: int,
    returned_chars: int,
    remaining_turns: int,
    *,
    session_saved: int,
    session_compounded: int,
    lifetime_saved: int,
    lifetime_compounded: int,
) -> str:
    """One line: raw, visible, avoided, and the exposure caveat. Totals live in local_metrics."""
    raw = tokens_from_chars(source_chars)
    visible = tokens_from_chars(returned_chars)
    avoided = max(0, raw - visible)
    if avoided == 0:
        ligne = (
            f"\n\nLocal-agent: ~{raw} tok read locally, ~{visible} returned, "
            "no content avoided (negative answer or source already smaller than the packet)"
        )
    else:
        ligne = f"\n\nLocal-agent: ~{raw} tok read locally, ~{visible} returned, ~{avoided} avoided this call"
    if remaining_turns <= 0:
        return ligne + " (exposure off: LOCAL_AGENT_COMPOUND_TURNS=0). Totals: local_metrics."
    exposure = tokens_from_chars(billed_chars(avoided * 4, remaining_turns))
    return ligne + (
        f" (~{exposure} token-turns over {remaining_turns} turns, not billed usage)."
        " Totals: local_metrics."
    )


def passthrough(
    title: str,
    raw: str,
    *,
    reason: str,
    stats: dict | None = None,
    details: str | None = None
) -> Report:
    """Return the raw evidence without calling the model, and say why."""
    report = Report(
        title=title,
        summary=f"Raw output, no synthesis: {reason}.",
        stats=dict(stats or {}, delegue=False, brut_caracteres=len(raw.strip()))
    )
    report.details = f"{details}\n\n{raw.strip()}" if details else raw.strip()
    return report
