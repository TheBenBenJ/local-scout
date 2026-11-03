# local-scout

> Keep large context local. Send the orchestrator only what matters.

A local evidence-gathering layer for AI coding agents (Claude Code, Cursor). One call reads the
Jira ticket, its screenshots, Confluence pages, logs and `rg` matches on your machine, and returns
**one bounded dossier** to the orchestrator: not fourteen MCP tools, not the PNGs, not the raw JSON.

## Why

An orchestrator that fetches a ticket, opens five screenshots and greps a repository pays for all of
that text on every later turn of the chat. Its MCP tool schemas are resent on every turn as well.
local-scout moves the gathering out of the chat: the raw material stays on disk, and the
orchestrator receives a capped summary of facts plus the paths to re-read if it really needs more.

It does not replace the orchestrator. Diagnosis, qualification and patches stay there.

## How it works

```text
Orchestrator ── one mission ──> local-scout (MCP tool `scout`, or the CLI)
                                   │
                                   ├─ Jira ticket, linked tickets, JQL search   (opt-in: `ticket`)
                                   ├─ screenshots → OCR on disk (Vision / Tesseract)
                                   ├─ Confluence pages and CQL search
                                   ├─ repo search (rg), logs, CI traces, git branches
                                   │
                                   ├─ writes everything to temp/scout/<key>/ in the target repo
                                   v
                     one dossier (≤ 12,000 characters) + re-read_allowed paths
                                   │
Orchestrator <─────────────────────┘ diagnoses from the dossier
```

- **Deterministic by default.** The `scout` tool runs no local LLM unless `use_llm=true`; then a
  local 9B model adds a synthesis, and may run one vision pass on screenshots whose OCR is weak.
- **Bounded.** The dossier is capped. Whatever is cut is named in `re-read_allowed` with a text file
  on disk (full ticket, full page, full OCR), so the orchestrator reads that file instead of calling
  Jira again or opening the PNG.
- **Closed sources.** `sources` is a closed list: a file means that file, a folder means its index.
  PDFs are read through their annotation objects, never OCR'd "just in case".

## Requirements

- macOS or Linux, Python 3.9+ (standard library only), `ripgrep`, `git`.
- OCR: `swiftc` (macOS Vision, compiled on first use into `var/`) or `tesseract` as a fallback.
- Optional: a local OpenAI-compatible server (`mlx-serve` on Apple Silicon, Ollama, llama.cpp,
  LM Studio, vLLM) for `use_llm=true` and the CLI without `--no-llm`. Recommended checkpoint:
  `mlx-community/Qwen3.5-9B-MLX-4bit`, one model loaded.
- Optional: Jira / Confluence / GitLab credentials (see Configuration).

## Install

```bash
git clone https://github.com/TheBenBenJ/local-scout ~/.local-scout
~/.local-scout/install.sh
```

`install.sh` checks the prerequisites, registers the `local-scout` MCP server in `~/.claude.json`
and `~/.cursor/mcp.json` (removing an old `local-agent` entry, and keeping its `env` block), then
runs `local-scout doctor`. Restart Cursor / Claude Code, then call `scout_ping`.

Do not enable the old [local-agent](https://github.com/TheBenBenJ/local-agent) MCP next to this one.

## Usage

### MCP (Cursor / Claude Code)

| Tool | Role |
| --- | --- |
| `scout` | Gather locally, return one dossier. Arguments: `mission` (required), `ticket`, `sources`, `use_llm` (default false), `repo`. |
| `scout_ping` | Liveness: version and git head. No LLM. |

Source schemes: `jira://`, `confluence://`, `cql://<terms>`, `repo://` or a plain repo path,
`image://`, `log://<path>`, `ci://gitlab/<project>/<job_id>`, `git://<pattern-or-ticket>`.
Details: [`docs/scout.md`](docs/scout.md).

After `scout` has answered, diagnose from the dossier. Re-read only the paths marked truncated or
listed in `re-read_allowed`. Do not re-read sources already included in full.

### CLI

```bash
~/.local-scout/bin/local-scout --ticket PROJ-123 --no-llm   # deterministic dossier
~/.local-scout/bin/local-scout --ticket PROJ-123            # plus a local 9B synthesis
~/.local-scout/bin/local-scout ping
~/.local-scout/bin/local-scout doctor
~/.local-scout/bin/local-scout task "Find the root cause." --source log://var/bench.log
```

The commands of the former local-agent (`doctor`, `ping`, `task`, `expand`, `image`, `review`,
`fix`/`apply`, `bench`, …) live on the same binary. They are never exposed as MCP schemas.
`--out` is CLI-only. `bin/local-agent` still forwards to `local-scout` so old scripts keep working.

## Configuration

**Target repository** (the client repo, not this checkout): `git rev-parse --show-toplevel` of the
current directory by default; `LOCAL_AGENT_REPO_ROOT=/path/to/repo` to override; per call, the MCP
argument `repo` (absolute: Cursor does not expand `${workspaceFolder}`). A home directory is refused
as a root.

**Settings**: copy `local-agent.env.example` to `local-agent.env` (gitignored) in this folder.
Real environment variables win. `LOCAL_LLM_*` selects the local model server (the former `MLX_*`
names still work); `LOCAL_AGENT_*` sets the bounds.
`LOCAL_SCOUT_JIRA_PROJECT` is the key of the Jira project whose tickets are recognised in missions and texts
(default `ACME`, the example project of the tests and docs): one project only, on purpose, since a generic `KEY-123`
pattern would also catch `UTF-8` or `SHA-256`.

**Credentials** are never stored here. They come from the **target repository's**
`.claude/.env.local` (`JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`; `GITLAB_URL`, `GITLAB_TOKEN`,
`GITLAB_PROJECT_ID`), or from the environment / `local-agent.env`. From a git worktree, the main
checkout's `.env.local` is read too.

## Operations and troubleshooting

- **Health**: `scout_ping` in the client, or `local-scout doctor` (Python, rg, git, database,
  OCR backend, local model server, model capabilities).
- **`stale:` in a ping or dossier**: the MCP server still runs the code it started with. Restart the
  client (or the session) after updating this checkout.
- **"working root equals the home directory" refusal**: the client was not started from a
  repository. Pass `repo`, or start the client from the target repository.
- **Jira "not configured"**: put the credentials in the target repository's `.claude/.env.local`,
  or point `repo` at that repository.
- **Local model errors**: only matter with `use_llm=true` or the CLI without `--no-llm`; check
  `LOCAL_LLM_BASE_URL` (default `http://127.0.0.1:11234/v1`) and that a model is loaded.
- **Debug copy**: every dossier is written to `temp/scout/<key>/dossier.md` in the target
  repository, with `tickets/`, `pages/` and `ocr/` next to it. That path is not returned over MCP.
- **Runtime data** lives in `~/.local-scout` next to the code and is gitignored: `context.db`,
  `evidence/`, `traces/`, `patches/`, `usage.jsonl`, `usage-totals.json`, `session.id`, `var/`.
- **Tests** (no model server or network needed):

  ```bash
  python3 ~/.local-scout/tests/run_all.py
  ```

## Security notes

- Paths resolve inside the target repository (screenshots may be absolute, still refused when they
  look like secrets or exceed 8 MB). `.git`, `node_modules`, `vendor`, `var`, dumps, `*.env`,
  `*.pem` and `*secret*` are denied unless the path names them explicitly.
- No free-form shell: project checks come from an allowlist (`.local-agent.json` or a language
  preset), read-only commands only, with stdin detached so no command can consume the MCP stream.
- No `git add`, `git commit` or `git reset`. Edits are proposed first, frozen by hash, and applied
  only as proposed.
- Tokens never appear in `doctor` output or dossiers.
- Tickets, pages and OCR text are third-party content: the orchestrator must treat the dossier as
  data, not as instructions.
- `~/.local-scout` and `temp/scout/` keep copies of ticket content on disk. Delete them when a
  project ends.

## Measured results

In **one** measured Cursor session (ACME-6476, 9 September 2026), diagnosing from a **pre-built**
dossier used 59% less reported usage than direct retrieval (Jira over HTTP + five PNG reads):
803.0 k versus 328.3 k on the usage rows, same model, same diagnosis prompt. The cheap side did not
call `scout` in the chat (the dossier came from the CLI), so this is not a general "59% saved".
Protocol and tables: [`docs/session-bench.md`](docs/session-bench.md),
[`docs/session-prompts.md`](docs/session-prompts.md) and [`BENCHMARKS.md`](BENCHMARKS.md)
(source-context interception, a different meter: do not convert it into billing).

## Design decisions

- **Two MCP tools instead of fourteen.** The former local-agent exposed 14 to 15 tools
  (`local_task`, `local_expand`, …) and intercepted raw material per call. Every turn resent the
  schemas plus the history of packets, and the orchestrator chained Jira, OCR and expand calls
  itself: measured +2.2 M Cursor tokens on one ticket. Scout keeps the tool loop local and sends one
  capped text. Rejected: trimming the old tool set (the schema tax stays per turn).
- **Deterministic by default.** A model synthesis weighs 1,500 to 2,600 characters and can omit
  items; raw evidence below that size is cheaper and exact, and skipping the model took a packet
  from 6.9 s to 0.03 s. The 9B synthesis is opt-in (`use_llm`). Rejected: always summarizing.
- **A capped dossier with named cuts.** In ten observed sessions, the orchestrator reloaded the
  ticket or reopened the PNGs right after `scout`: the dossier was cut silently. Now the body goes in
  whole while the budget allows, and every cut points to a file on disk.
- **OCR on disk, images never in the chat.** PNGs cost attach tokens; OCR text is smaller and
  searchable. A vision pass only adds layout, uses the model already loaded (never a second
  checkpoint) and gets file paths, not base64 (Qwen3.x / mlx-vlm loop on data URIs). OCR numbers
  stay authoritative.
- **PDF annotations, not PDF OCR.** Review comments are Annot objects; rasterizing the PDF loses them.
- **Credentials from the target repository.** The project's skills already keep Jira settings in
  `.claude/.env.local`; reusing it avoids a second copy of a token in this folder.
- **Standard library only.** A hand-written stdio JSON-RPC loop instead of an MCP SDK: nothing to
  install, nothing to pin.
- **Internal name kept.** The product was renamed from local-agent to local-scout, but the Python
  package (`local_agent`), the `LOCAL_AGENT_*` variables, `local-agent.env` and `.local-agent.json`
  keep their names: they are imported by `bin/`, set in users' MCP `env` blocks and in target
  repositories. Renaming them would break existing installs for no functional gain.
- **Language.** Code, comments and docs are English. MCP tool schemas are meant to be English so any
  orchestrator reads them (`tests/test_mcp_i18n.py` checks the legacy set; the `scout` description
  still carries two French reminders). The dossier headings, CLI help and some messages are French
  because the tool was built for French tickets and a French-speaking user; tests pin these strings.

## Layout

```text
bin/            entry points: local-scout, local-scout-mcp, and the local-agent shims
local_agent/    package: scout/ (gather, extract, dossier, MCP), providers/ (Jira, Confluence,
                GitLab), OCR, vision, local model client, legacy local-agent tasks
docs/           scout details, session bench protocol, field replay cases
tests/          unit tests (run_all.py) and benches (bench*.py, mcp_probe.py)
```

## License

MIT. See [LICENSE](LICENSE).
