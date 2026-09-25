# Sentinel tutorial: the codebase, one subsystem at a time

This course is for an engineer who wants to understand Sentinel well enough to
change any part of it and explain why each part is built the way it is. It
assumes you read Python and some TypeScript. It does not assume orbital
mechanics, CRDTs or NATS: each chapter explains the ideas it needs.

The course differs from the reference documents. `docs/technical-guide.md`
tells you where everything is and how to configure it, and
`docs/system-design.md` records the decisions. This tutorial walks you through
the code in the order that makes it make sense, with something to run at every
step. The course ends by following one conjunction message through the whole
system.

## Before you start

```bash
export PATH=$HOME/.local/bin:$PATH
uv sync --locked --python 3.12 --extra dev     # exactly what CI installs
uv run pytest -q                               # the whole ladder; 0 skipped
make help                                      # every target, one line each
```

Some chapters run real processes, a hub and an edge node over an emulated
link. They need the pinned binaries (`make tools`, sha256-verified) and the
console build (`make web`). `make demo-local` does both, then starts a hub on
:8000 and an edge on :8001.

## Reading order

Chapters 1 to 5 describe one node. Chapters 6 to 9 cover two nodes and a bad
link. Chapters 10 and 11 are the mission modules built on top. Chapters 12
and 13 explain how the software is shipped and how it is kept honest.
Chapter 14 puts it all together.

| # | Chapter | You will be able to |
|---|---|---|
| 1 | [Orientation](01-orientation.md) | name every top-level part, run each one, and say which chapter covers it |
| 2 | [The risk engine](02-risk-engine.md) | explain what a Pc is, why a low one can mislead, and when the engine refuses |
| 3 | [CDMs, ingest and events](03-cdm-and-events.md) | follow a CDM from bytes to an assessed, banded event |
| 4 | [The node and its API](04-node-and-api.md) | trace any HTTP route or live event to the code behind it |
| 5 | [The operator console](05-console.md) | find any screen's data source and know why a Pc renders only one way |
| 6 | [The bus and the link](06-bus-and-links.md) | say what crosses a link, what never does, and how link state is measured |
| 7 | [Priority sync](07-priority-sync.md) | explain how an edge chooses what to fetch first and when it trusts a result |
| 8 | [Operator data: signed CRDTs](08-operator-data.md) | explain how decisions made offline merge without loss |
| 9 | [The DDIL harness](09-ddil-harness.md) | run a scenario on real processes and read its report |
| 10 | [Passes and screening](10-passes-and-screening.md) | explain the pass module and why a unit's position never leaves its node |
| 11 | [The AI assistant: a safety pattern](11-ai-assistant.md) | explain why the AI can route and phrase but never compute |
| 12 | [Supply chain and deployment](12-supply-chain-and-deploy.md) | build, sign, verify and install a bundle with no network |
| 13 | [Keeping it honest: guardrails, compliance and the trace](13-guardrails-compliance-mbse.md) | say which check fails when a doc, a boundary or a requirement drifts |
| 14 | [End to end: one CDM through the whole system](14-end-to-end.md) | narrate the full path, command by command |

## How each chapter is laid out

Every chapter uses the same sections, so you always know where to look:

- **What you will learn**: the chapter's goals in three to five lines.
- **Why it exists**: the operator problem this code solves, and what it buys them.
- **Concepts**: the ideas you need before reading the code, in plain language.
- **Code walkthrough**: the files in reading order, and in each one the functions that matter and the one part that is easy to get wrong.
- **Try it**: commands to run, and what to look for in their output.
- **Design choices**: what the code buys, what it costs, and what was rejected, with a link to the ADR.
- **How it fails**: what the code does with bad input or a bad link, and how that failure is shown to the operator rather than hidden.
- **Check yourself**: questions, each with its answer folded underneath.
- **Where next**: the chapters and reference documents to read after this one.

Code is named by path and symbol (for example `sentinel/risk/engine.py`,
`assess`), not by line number, so the course stays accurate as the code
moves. The doc checks in `tests/test_docs.py` fail when a path named here
stops existing.
