# Domain Docs

How the engineering skills should read this repo's domain documentation before exploring the code.

## Layout: single-context

Sentinel is one context. Its domain record is:

- `docs/system-design.md`: the architecture, and every ADR as `### ADR-NNN — Title` in section 3.
- `docs/risk-engine-design.md`: the maths behind the risk engine.
- `docs/technical-guide.md`: the configuration reference and the "How to extend" recipes.
- `CONTEXT.md` at the repo root: the glossary. It doesn't exist yet.

## Before exploring, read these

- **`CONTEXT.md`**, if it exists.
- **The ADRs in `docs/system-design.md`** that touch the area you're about to work in.

If `CONTEXT.md` doesn't exist, **proceed silently**. Don't flag its absence; don't suggest creating it upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates it lazily when a term actually gets resolved.

## Where a new ADR goes

Append it to section 3 of `docs/system-design.md` as the next `### ADR-NNN — Title`. Don't start a separate ADR directory, even where a skill defaults to one: `tests/docs/test_value_first.py` checks ADRs only in `docs/system-design.md`.

Match the twelve already there:

- **Buys.** first: what the decision gives an operator, in their terms, with its measured number.
- **Costs.** next: what it costs. The test fails an ADR that doesn't open with these two lines.
- Then **Status:**, **Decision.** and **Rejected.**

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-008 (reference data by priority pull), but worth reopening because…_
