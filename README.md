# local-scout

![Keep large context local. Send the orchestrator only what matters.]

> Keep large context local. Send the orchestrator only what matters.

A local evidence-gathering layer for AI coding agents. One pass over Jira, screenshots, Confluence and `rg`. The orchestrator receives **one compact dossier**, not fourteen MCP tools and not the PNGs.

```text
Orchestrator
    |
    | one mission
    v
local-scout
    |
    + Jira
    + screenshots / OCR
    + Confluence
    + repo search
    |
    v
one compact dossier
    |
    v
Orchestrator diagnoses
```

It does not replace the orchestrator. Diagnosis, qualification and patches stay there.

Do not enable the old [local-agent](https://github.com/TheBenBenJ/local-agent) MCP next to this one.

## Quick start

```bash
git clone https://github.com/TheBenBenJ/local-scout ~/.local-scout
~/.local-scout/install.sh
```

Requires Python 3.9+ (stdlib only), `ripgrep`, `git`. A local OpenAI-compatible server (`mlx-serve` on Apple Silicon) is optional: the MCP path is **deterministic by default** (0 local LLM). Restart Cursor / Claude Code, then call `scout_ping`.

```bash
~/.local-scout/bin/local-scout --ticket LYSI-6476 --no-llm
~/.local-scout/bin/local-scout --ticket LYSI-6476
~/.local-scout/bin/local-scout doctor
```

Install writes `local-scout` into `~/.cursor/mcp.json` and `~/.claude.json`, and removes `local-agent` if it was still registered.

## MCP (Cursor / Claude Code)

Two tools only:

| Tool | Role |
| --- | --- |
| `scout` | Gather locally, return one dossier. Default: no local LLM. Pass `use_llm=true` to add a 9B synthesis. |
| `scout_ping` | Liveness. Version and git head. No LLM. |

After `scout` has answered: diagnose from the dossier. Re-read only paths marked truncated, or ids requested as drill-down. Do not re-read sources already included in full. The dossier is also written under `temp/scout/<key>/` in the target repo for debug. That path is not returned over MCP.

End-to-end session protocol (A / B / C): [`docs/session-bench.md`](docs/session-bench.md).
Ticket replay prompts (LYSI-6160 / 6417 / 6553) and dossier scoring: [`docs/session-prompts.md`](docs/session-prompts.md).

## CLI

Same binary. Subcommands that used to live on `local-agent` (`doctor`, `ping`, `task`, `expand`, `image`, …) are on `local-scout`. They never appear as MCP schemas. `--out` is CLI-only.

```bash
~/.local-scout/bin/local-scout ping
~/.local-scout/bin/local-scout doctor
~/.local-scout/bin/local-scout task "Find the root cause." --source log://var/bench.log
```

`bin/local-agent` still forwards to `local-scout` so old scripts do not break.

## Measured Cursor session (LYSI-6476)

In **one** measured Cursor session, diagnosing from a **pre-built** scout dossier used 59% less reported usage than direct retrieval (Jira over HTTP + five PNG Reads). Same model (`cursor-grok-4.6-high-fast`), two fresh chats, then the same 15-line diagnosis prompt. Usage **rows**, not the 7-day account total.

| Phase | Without scout (direct retrieval) | Pre-built `dossier.md` on disk | Difference |
| --- | ---: | ---: | ---: |
| Gather | 422.7 k | 60.5 k | 362.2 k |
| Analyse (15 lines + grep) | 380.3 k | 267.8 k | 112.5 k |
| **Session** | **803.0 k** | **328.3 k** | **474.7 k (59 %)** |

This is not “local-scout saves 59% tokens” in general. The cheap side did **not** call `scout` in-chat: the dossier was produced earlier by the CLI (12.5 s; 9B tokens stayed on the machine). It is not a full `/analyse` recette. A session that pays the MCP schema tax **and** calls `scout` once is a different measurement: see [`docs/session-bench.md`](docs/session-bench.md).

Source-context interception in [`BENCHMARKS.md`](BENCHMARKS.md) is a different meter. Do not convert it into Cursor billing.

## Jira / Confluence

Credentials are not stored here. They come from the **target repo's** `.claude/.env.local` (`JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`) or from the environment / `~/.local-scout/local-agent.env`. Tokens never appear in `doctor` or reports.

## Model

Recommended checkpoint when `use_llm=true` or the CLI omits `--no-llm`: **`mlx-community/Qwen3.5-9B-MLX-4bit`**. Keep one model loaded. MCP synthesis is opt-in.

Images: OCR on disk first. PNGs stay out of the chat. When `use_llm=true` and the loaded
checkpoint declares vision, up to 3 screenshots per mission whose OCR is weak (empty, or the
mission hints at layout — merged headers, disabled buttons, filters) get one extra local vision
pass. OCR numbers stay authoritative; vision only fills layout OCR cannot capture.

## Configuration

Root of the **client** repository, not this checkout:

- default: `git rev-parse --show-toplevel`
- override: `LOCAL_AGENT_REPO_ROOT=/path/to/client/repo`
- per call: MCP argument `repo` (absolute). Cursor does not expand `${workspaceFolder}`.

Copy `local-agent.env.example` to `local-agent.env` (gitignored). Real environment variables win. `MLX_*` names still work if `LOCAL_LLM_*` is unset.

## Safety

Paths resolve inside the repository root (images may be absolute, still refuse secrets and >8 MB). `.git`, `node_modules`, `vendor`, `var`, dumps, `*.env` / `*.pem` / `*secret*` are denied unless the path names that directory explicitly. CLI writes default to propose-then-apply. No `git reset`, `git add`, or `git commit` from the tool.

## Tests

```bash
python3 ~/.local-scout/tests/run_all.py
python3 ~/.local-scout/tests/test_scout.py
```

## Development

Public version: **1.5.1** (`local_agent/version.py`). Python package name remains `local_agent`. Product and MCP name: `local-scout`.

After MCP code changes, restart the client.

## License

MIT. See [LICENSE](LICENSE).
