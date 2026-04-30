# Prompts used to build this project

A chronological record of the user-side prompts that drove the development of
this repo. Useful as a reference for how a "vibe-coding" project converges
from a single design brief into working code.

---

## 1. The design brief (Stage 0)

The repo was bootstrapped by handing Claude the file
[`monopoly_handoff.md`](./monopoly_handoff.md) — a multi-page document laying
out goals, build order, architectural principles (state-machine engine,
actions-as-data, RuleSet config, event log), and rules-gotchas to model
correctly.

Effective prompt:
> @monopoly_handoff.md

That single document carried essentially all the project intent. Everything
below is incremental clarification on top of it.

---

## 2. Stage 1 — clarifying answers

After Claude proposed building the movement-only simulator and asked four
clarifying questions (data file format, output format, Python version,
directory layout), the answer was:

> I prefer YAML, and for output a CSV would be best. No preference on Python
> version or directory layout.

That settled the data-file format (YAML) and the report format (CSV). Stage 1
landed in one pass: data files + loader + `MovementSimulator`, validated
against Truman Collins's published landing frequencies.

---

## 3. Stage 2 — kickoff

After Stage 1 was complete and validated, the model was switched to Opus and
effort raised to auto, then:

> Please proceed with Stage 2.

That triggered the full state-machine engine, action/event/decision types,
RuleSet, RandomPlayer, HeuristicPlayer, runner, ASCII renderer, and CLI.
Auctions and trading were stubbed for Stage 5 per the handoff doc.

---

## Notes for future stages

- Stage 3 (human CLI player), Stage 4 (MCP server), Stage 5 (auctions +
  trading + building polish), and Stage 6 (web UI) are all defined in
  [`monopoly_handoff.md`](./monopoly_handoff.md).
- The architectural principles in that doc are load-bearing: future stages
  should add new decision and action types, **not** restructure the engine.
