# local-scout

![Keep large context local. Send the orchestrator only what matters.](docs/architecture.jpg)

One local pass over Jira, screenshots, Confluence and `rg`. Cursor / Claude Code see a **bounded dossier** (≤ 12 000 characters), not fourteen MCP tool schemas and not the PNGs.

> Keep large context local. Send the orchestrator only what matters.

Successor of [local-agent](https://github.com/TheBenBenJ/local-agent). The 14-tool MCP (`local_task`, `local_expand`, …) is gone: those schemas were billed every turn. Fine-grained tools remain on the **CLI**, outside the chat.

It does not replace the orchestrator. Diagnosis, qualification and patches stay there.

## Why

Per-call interception does not save a Cursor conversation. A 14-tool MCP plus `expand` on every turn costs more than it hides. Scout inverts the flow:

```text
scout(mission="LYSI-6476 …", ticket="LYSI-6476")
→ Jira + OCR + Confluence + rg, on the machine
→ dossier ≤ 12 000 characters
→ the orchestrator diagnoses
```

Do not enable the old `local-agent` MCP next to this one.

## Quick start

```bash
git clone https://github.com/TheBenBenJ/local-scout ~/.local-scout
~/.local-scout/install.sh
```

Requires Python 3.9+ (stdlib only), `ripgrep`, `git`, and an OpenAI-compatible local server (`mlx-serve` on Apple Silicon is what we measure against). Restart Cursor / Claude Code, then call `scout_ping`.

```bash
~/.local-scout/bin/local-scout --ticket LYSI-6476
~/.local-scout/bin/local-scout --ticket LYSI-6476 --no-llm
~/.local-scout/bin/local-scout doctor
~/.local-scout/bin/local-scout bench --ticket LYSI-6476 --out temp/scout/bench
```

Install writes `local-scout` into `~/.cursor/mcp.json` and `~/.claude.json`, and removes `local-agent` if it was still registered.

## MCP (Cursor / Claude Code)

Two tools only:

| Tool | Role |
| --- | --- |
| `scout` | Gather locally, return one dossier |
| `scout_ping` | Liveness (repo, OCR, MLX). No LLM |

After `scout` has answered: do not Read the PNGs, do not re-fetch Jira, do not Read `dossier.md` a second time.

## CLI

Same binary. Subcommands that used to live on `local-agent` (`doctor`, `ping`, `task`, `expand`, `image`, …) are on `local-scout`. They never appear as MCP schemas.

```bash
~/.local-scout/bin/local-scout ping
~/.local-scout/bin/local-scout doctor
~/.local-scout/bin/local-scout task "Find the root cause." --source log://var/bench.log
~/.local-scout/bin/local-scout expand LOG-E1
```

`bin/local-agent` still forwards to `local-scout` so old scripts do not break.

## Measured Cursor session (LYSI-6476)

Same model (`cursor-grok-4.6-high-fast`), two fresh chats, then the **same** 15-line diagnosis prompt. Usage **rows**, not the 7-day account total.

| Phase | Without scout (A) | Dossier already on disk (B) | A − B |
| --- | ---: | ---: | ---: |
| Gather | 422.7 k | 60.5 k | 362.2 k |
| Analyse (15 lines + grep) | 380.3 k | 267.8 k | 112.5 k |
| **Session** | **803.0 k** | **328.3 k** | **474.7 k (59 %)** |

A loaded Jira over HTTP and Read five PNGs. B Read `dossier.md` once (produced earlier by the CLI in 12.5 s; 9B tokens stay on the machine). This is not a full `/analyse` recette. Detail: [`docs/scout.md`](docs/scout.md).

Source-context interception in [`BENCHMARKS.md`](BENCHMARKS.md) is a different meter. Do not convert it into Cursor billing.

## Jira / Confluence

Credentials are not stored here. They come from the **target repo's** `.claude/.env.local` (`JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`) or from the environment / `~/.local-scout/local-agent.env`. Tokens never appear in `doctor` or reports.

## Model

Recommended default: **`mlx-community/Qwen3.5-9B-MLX-4bit`**. Keep one model loaded. Scout synthesis is optional (`--no-llm` is deterministic extract only).

Images: OCR on disk first. PNGs stay out of the chat.

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

Public version: **1.5.0** (`local_agent/version.py`). Python package name remains `local_agent` (extractors, OCR, store). Product and MCP name: `local-scout`.

After MCP code changes, restart the client.

## License

MIT. See [LICENSE](LICENSE).
