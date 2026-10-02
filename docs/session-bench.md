# Session bench A / B / C

This measures **Cursor / Claude usage for a whole chat**, not source-context interception.

Do not convert [`BENCHMARKS.md`](../BENCHMARKS.md) `interception_rate` into this table.

## Same task

Ticket: **LYSI-6476** (Jira + screenshots + repo). Same attachments, same repo HEAD, same model, same user prompt. New chat per scenario. No copy-paste of a previous dossier into A or B.

Suggested mission text (identical in A, B, C):

```text
Diagnostiquer LYSI-6476. Ne pas corriger. Qualifier ensuite.
```

Record Usage **rows** for that chat, not the 7-day account total. Keep input, output, cache read, cache write separate if the UI shows them. Do not invent a blended “cost” if the product does not.

## A — baseline, MCP off

Disable `local-scout`. New chat. Give only the mission. The orchestrator uses its usual tools (HTTP, Read, grep).

Save: input / output / cache read / cache write / total shown / tool-call count / duration / diagnostic quality (0–3).

## B — MCP on, `scout` not called

Enable `local-scout`. New chat. Same mission, **do not** call `scout`. A comparable witness task is acceptable if the product forces a first-tool call; the point is the **schema tax** of the two tools.

`B − A` approximates the standing cost of exposing the MCP.

## C — `scout` once

Enable `local-scout`. New chat. Same mission. Call `scout` **once** (default: no local LLM). Diagnose from the returned dossier. Do not reopen Jira / PNGs / large files unless a proof is actually missing. Any reopen is a **fallback / scout miss**.

## Deltas

```text
MCP fixed overhead = B − A
Scout workflow delta = C − A
Scout incremental value = C − B
```

Quality: 0 incorrect, 1 partial, 2 correct but thin evidence, 3 correct with enough evidence. Score A and C with the same grid.

Success on this case: `C < A` by a clear margin **and** quality C ≥ quality A. `C ≈ A` is comfort, not a context win. `C > A` invalidates the thesis on this workload: name whether the surplus is schemas, dossier, tool calls, LLM summary, fallbacks, re-reads, or extra turns.

## Not measured in the 1.5.1 code drop

A / B / C must run as **three fresh chats**. They cannot share the conversation that implemented the code. Fill the table below when those chats exist.

Replay prompts for the later terrain tickets (6160, 6417, 6553) and the dossier scoring harness: [`session-prompts.md`](session-prompts.md).

```bash
~/.local-scout/bin/local-scout bench --print-prompt LYSI-6553-c2
~/.local-scout/bin/local-scout bench --cases --repo /chemin/vers/lysi --out temp/scout/bench-terrain
```

| | A | B | C |
| --- | --- | --- | --- |
| input | | | |
| output | | | |
| cache read | | | |
| cache write | | | |
| tool calls | | | |
| duration | | | |
| quality 0–3 | | | |
