# Scout

The orchestrator no longer chains Jira / OCR / expand calls. Deterministic
extractors gather Jira, attachments, Confluence and `rg` results, and a single
dossier of at most 12,000 characters comes out. The 9B model only runs when
asked (`use_llm` on the MCP side, no `--no-llm` on the CLI side).

Repository: https://github.com/TheBenBenJ/local-scout

## Why

The 14-tool MCP (`local_task`, `local_expand`, …) intercepted raw material **per call**.
Over a conversation, every turn sent the tool schemas back, plus the history of packets.
Measured on ACME-6476 "with local-agent": +2.2 M Cursor tokens.

## Install

```bash
git clone https://github.com/TheBenBenJ/local-scout ~/.local-scout
~/.local-scout/install.sh
```

MCP: `scout` and `scout_ping` only. `scout` is deterministic by default.
`--out` only exists on the CLI.

One call per mission. Diagnose from the dossier. Re-read only the paths
marked truncated, listed in `re-read_allowed`, or the ids requested as a
drill-down. `sources` is a closed list: a file means that file, a folder
means its index. PDF: Annot objects first, never an OCR of the document
"just in case". A Jira ticket is fetched only when `ticket` is given.

Source schemes: `repo://`, `jira://`, `confluence://`, `image://`,
`log://<path>` (local file: failures plus context kept, repetitive noise
de-duplicated), `ci://gitlab/<project>/<job_id>` (GitLab job trace, same
filtering as `log://`, credentials in `.claude/.env.local`: `GITLAB_URL`,
`GITLAB_TOKEN`, `GITLAB_PROJECT_ID`), `git://<pattern>` (local branches whose
name or history carries the pattern, with their merge status into
main/master/develop: gathering only, no opinion on which branch is right).

`cql://<terms>` runs a Confluence full-text search (titles, pageId, quote, body
on disk). Pages are written whole under `temp/scout/<key>/pages/`; "full
text" is only written when it is true. Up to 20 screenshots go through OCR, 8 are
shown, the others are named in `re-read_allowed` with their OCR file. The ticket
is also written as the API returns it (`tickets/<key>.json`), for skills that want
a `contexte.json` without a second Jira call. The MCP envelope carries a `ramassage:`
line (characters and images read locally versus characters returned).

OCR first for screenshots. With `use_llm=true` and a model that declares
vision, up to 3 screenshots per mission whose OCR is not enough (empty
transcript, or the mission hints at a layout gap: merged header, filter,
disabled button) get a second vision pass, for layout only: the numbers
remain those of the OCR.

```
scout(mission="Diagnose PROJ-123 …", ticket="PROJ-123")
```

CLI:

```bash
~/.local-scout/bin/local-scout --ticket PROJ-123 --no-llm
~/.local-scout/bin/local-scout --ticket PROJ-123
~/.local-scout/bin/local-scout doctor
```

Output on disk: `temp/scout/<key>/dossier.md` in the target repository (debug).
That path is not returned in the MCP response.

A/B/C session protocol: [`session-bench.md`](session-bench.md).
Field prompts 6160 / 6417 / 6553 and scoring grid: [`session-prompts.md`](session-prompts.md).

## What the session review changed (2 Oct 2026)

Ten `scout` calls found in the Claude Code transcripts from 14/09 to 01/10: in all ten,
the orchestrator reloaded the ticket or reopened the PNGs right afterwards. Causes fixed:

- ticket body cut at 600 characters / 8 lines while the dossier only used a third of its
  cap: the body now goes in whole as long as the budget allows;
- no comments, links, priority or custom fields: they are now rendered, the fields named
  in the mission first ("empty in Jira" when they are);
- off-topic Code section (patterns of a planning ticket hard-coded): the screen search
  starts from the ticket's URLs and symbols, and does not run for an "Extraire…" mission;
- `ready: false` every time for lack of a Confluence page, searched with the verbs of the
  instruction: an extraction mission requires neither a page nor a screen, and the query
  starts from the ticket title;
- OCR reduced to a few keyword-filtered lines: the transcript now follows reading order,
  bounded per image, in full in `temp/scout/<key>/ocr/<image>.txt`;
- an image passed as an absolute path was marked "not extracted"; Jira was "not configured"
  from a git worktree (the main checkout's `.env.local` is now read).

Whatever is cut is named in `re-read_allowed` with a text file on disk
(`temp/scout/<key>/tickets/<key>.md`): the drill-down reads that file.

## Cursor measurement (ACME-6476, 9 Sept 2026)

In **one** measured session, diagnosing from a scout dossier **already written
to disk** used 59% less reported usage than direct retrieval (Jira over HTTP +
five PNGs). This is not "local-scout saves 59% of tokens" in general: the cheap
chat did not call `scout`. It is not a full `/analyse` run either.

| Phase | Without scout | Dossier already there | Saving |
| --- | ---: | ---: | ---: |
| Gather | 422.7 k | 60.5 k | 362.2 k |
| Analysis | 380.3 k | 267.8 k | 112.5 k |
| Session | 803.0 k | 328.3 k | **474.7 k (59%)** |

## Internal counters

`raw_chars` / `ledger.text_chars`: text of the sources, on disk.
`visible_chars`: length of the dossier, on disk. Not in the MCP response.
PNG bytes: `ledger.image_bytes`. A local interception percentage is not
a delta of Cursor usage cards.
