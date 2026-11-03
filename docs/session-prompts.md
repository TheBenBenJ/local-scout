# Field replay prompts and dossier bench

Five **fresh** chats, workspace = the client repository the cases were taken from (not
`~/.local-scout`). MCP `user-local-scout` at version **1.8.x** or later (check with `scout_ping`).
`use_llm=false`. One `scout` call per chat.

The automatic score is about the **dossier**, not the Cursor usage cards. Usage rows are filled in
by hand, as in [`session-bench.md`](session-bench.md).

The exact chat prompts are French, like the tickets they replay. They live in
`local_agent/scout/cases.py` and are printed by the CLI, so this page only summarizes them.

## Print / score

```bash
# Prompt ready to paste
~/.local-scout/bin/local-scout bench --print-prompt ACME-6160
~/.local-scout/bin/local-scout bench --print-prompt ACME-6417-pdf
~/.local-scout/bin/local-scout bench --print-prompt ACME-6417-dir
~/.local-scout/bin/local-scout bench --print-prompt ACME-6553-c1
~/.local-scout/bin/local-scout bench --print-prompt ACME-6553-c2

# Grid on the client repository (real Jira, --no-llm)
cd /path/to/client/repo
~/.local-scout/bin/local-scout bench --cases --repo . --out temp/scout/bench-terrain

# Score a dossier.md produced in a chat
~/.local-scout/bin/local-scout bench --score-dossier temp/scout/ACME-6553/dossier.md --case ACME-6553-c2 --repo .
```

Cases: `ACME-6160`, `ACME-6417-pdf`, `ACME-6417-dir`, `ACME-6553-c1`, `ACME-6553-c2`.

## How to play a chat

1. New chat, workspace = the client repository.
2. Paste **one** prompt (the output of `--print-prompt`).
3. Check `scout_ping` → `version: 1.8.0` (or later).
4. The agent calls `scout` **once** and diagnoses from the dossier.
5. Any Read / Jira curl / PNG outside `re-read_allowed` = **scout miss** (fallback).
6. Fill in the Usage row and the grid. Score the dossier with `--score-dossier`.

Diagnosis quality (A and C): 0 wrong, 1 partial, 2 right but thin evidence, 3 right with enough evidence.

| Chat | input | output | cache r | cache w | tools | duration | quality 0–3 | fallbacks | bench % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 6160 | | | | | | | | | |
| 6417-pdf | | | | | | | | | |
| 6417-dir | | | | | | | | | |
| 6553-c1 | | | | | | | | | |
| 6553-c2 | | | | | | | | | |

`C < A` is **not** the criterion here: this measures whether the 1.8 dossier holds the field gaps.
A chat A (MCP off) stays optional, ticket by ticket, if you want a Usage delta.

---

## ACME-6160 — code review

Original failure: a `lib/…/src/…` connector path rewritten as `src/…`, hence "named file missing";
excerpts from the wrong type; "Do not re-read" although the file was truncated.

Prompt: code review of a daily e-reporting handler (batch creation, routing). Exactly one `scout`
call with `ticket` and the connector file in `sources`, `use_llm=false`; no fix, qualify afterwards.

Scorecard (yes/no):
- the `lib/…` bundle path is kept, no "named file missing";
- the handler, the batch methods and the messenger routing named in the mission are all found;
- no invented "Trous" (gaps) section; truncation announced when the file is not complete;
- 0 fallback Read/curl outside the gaps.

## ACME-6417 — PDF Annots (file)

Original failure: no Annot extractor, OCR of the neighbouring PNGs, Jira fetched without `ticket=`.

Prompt: extract the yellow comments (Highlight Annots) of the review PDF attached to the ticket,
passing the PDF file itself in `sources`, no `ticket`, `use_llm=false`. If the exact path moved,
pass the real path of the same file (same basename), not its parent folder.

Scorecard:
- `ready_for_diagnosis` true when there are Annots, false otherwise, with gaps listed;
- Highlight `/Contents` present; faithful PDF path;
- no OCR of neighbouring files, no ticket dump;
- 0 PNG Read, 0 Jira curl.

## ACME-6417 — folder = index (separate chat)

Same mission, but `sources` is the **folder**, not the PDF: scout must index it, not extract the
Annots. Expected: `ready_for_diagnosis: false`, a gaps section, `re-read_allowed` pointing at the PDF.

Scorecard:
- index listing the PDF name;
- ready false; gaps / `re-read_allowed` towards the PDF file;
- no OCR of the folder's PNGs.

## ACME-6553 — call 1 (ticket + screen)

Original failure: "Trous : aucun" (no gaps) while Confluence, the `render` screen and the typing
of the `salarieId` URL parameter were missing; a controller picked only because of a `use()`;
an OCR "novel".

Prompt: diagnose a planned duration / counter / gauge stuck at 0 on a planning screen. Gather the
ticket, screenshots, the screen (the controller that renders it), the domain Confluence page and
the typed URL UUIDs; do not conclude absence without a gaps section. `ticket` given, `use_llm=false`.

Scorecard:
- compact `## Ticket` (type, status, ≤ 8 lines, typed UUIDs);
- the expected controller as the screen, not the one that merely `use()`s the service;
- Confluence (title + pageId + quote) OR a "not searched" gap;
- `ready_for_diagnosis` not true while a blocking gap is missing from the gaps section;
- 0 Jira curl, 0 PNG Read.

## ACME-6553 — call 2 (linked tickets + JQL)

Original failure: `sources` was set, so no JQL ran; Claude had to curl `search/jql`; the OCR of
linked ticket 6271 (a screenshot showing a person's name) was inlined in the 6553 dossier.

**Fresh chat**, do not paste the dossier of call 1.

Prompt: fetch five linked tickets **and** search for an existing ticket about the same defect, with
the linked tickets passed as `jira://` sources and `use_llm=false`. Scout must run the JQL even
though `sources` is set.

Scorecard:
- `## Recherche Jira` with the JQL, even with 0 candidates;
- no OCR of linked ticket 6271 (no "16 additional items omitted" from a linked OCR);
- the `:salarieId` UUID typed, with "this is not the planning id";
- the expected controller; the other one dismissed or marked "incidental mention";
- `## Trous` not empty (not "aucun") while Confluence is missing;
- 0 curl of `search/jql`.

Acceptance criterion for call 2: a Jira search section (even empty, with the JQL); gaps not empty
while Confluence and the typing are missing; no inlined OCR from linked ticket 6271.
