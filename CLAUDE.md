# Sentinel: repo rules

Sentinel is a DDIL-resilient conjunction assessment decision aid, with an overhead-pass mission module. The architecture record is in `docs/system-design.md` (ADRs) and the maths in `docs/risk-engine-design.md`.

## Commands

```bash
export PATH=$HOME/.local/bin:$PATH      # uv lives here
uv pip install -e ".[dev]"              # into .venv
uv run pytest -q                        # full suite; must report 0 skipped
uv run pytest -q -m tier4               # one rung of the ladder (tier1..tier6)
uv run ruff check . && uv run lint-imports
uv run python scripts/validation_report.py   # regenerates docs/validation-report.md
uv run sentinel --help                  # CLI
make help                               # all make targets
make trace && make sysml-check          # requirement trace (docs/traceability.md) and SysML v2 syntax
make screen PRIMARY=40115               # demonstration mode: element-set geometry, no Pc
make sbom scan airgap-selftest          # SBOMs, vulnerability gate, offline signature proofs
make airgap-local                       # build, sign (throwaway key), verify and install with no network
make ai-eval bench-passes               # score the AI routers; time the pass engine
```

## Non-negotiable rules

- **Units are field-name suffixes**: `_km`, `_km_s`, `_m`, `_m2`, `_m_s`, `_s`. The CDM carries km for states and m² for covariance. The engine works in metres.
- **`risk.assess()` never raises on bad data.** It returns `Method.REFUSED` with a `RefusalReason` and records the value that tripped the gate.
- **Ingest policy (ARMOR rule):** input that would make an answer *wrong* raises or quarantines. Input that makes it *incomplete* degrades with a warning. Both are recorded, never swallowed.
- **Never produce a Pc from element-set (TLE/OMM) data.** Demonstration mode gives geometry only (ADR-002).
- **A Pc never travels without its `method`.** In the web UI, a Pc renders only through the `PcValue` component, which takes the whole assessment object.
- **The test ladder comes first**: write the rung, watch it fail, then write the code.
- **CARA fixtures are transcribed by hand** from NASA's published files, with provenance. Never generate expected values by running this code.
- **Tests never touch the network** (`pytest-socket`). Skyfield loads bundled ephemerides only.
- **Generated files; regenerate them and never hand-edit:** `docs/validation-report.md`, `docs/ddil-results.md`, `docs/ai-eval.md` (with `docs/img/ai-reliability.svg`), `docs/traceability.md`, `deploy/vex/sentinel.openvex.json` and the OSCAL documents under `compliance/oscal/` (`make compliance`).
- **Docs are checked against the repo** (`tests/test_docs.py`): every path, `make` target and `sentinel` subcommand they name must exist, and every headline number registered in `tests/doc_claims.toml` must match its generated source. When a regenerated report changes a number, update the prose and the registry together.
- **AI never computes.** The assistant (`sentinel/ai/`) routes to tools and phrases their facts; `.importlinter` forbids it the maths. Hosted AI (Jev, Claude) needs an UNCLASSIFIED marking, operator opt-in and a usable measured link, and every AI answer passes the number-grounding guard. Never publish a Jev number that did not come from a real run.
- **Module boundaries are enforced by `.importlinter`**: `bus`, `triage`, `sync`, `crdt`, `ops` and `linkstate` may not import mission modules (`conjunction`, `risk`, `cdm`, `passes`) or the API.
- **Data class on everything**: REAL, DERIVED or EXERCISE. Exercise data carries `ORIGINATOR=SENTINEL-EXERCISE`.
- **Requirement-to-evidence mapping lives in `mbse/verification.sysml`**, not in pytest markers. Unbuilt work is marked `@Planned` and must show as unverified, never verified.
- **Passes: a gap is "not observed by catalogued imagers", never "safe".** A provider asked about an imager it has no data for raises `ImagerNotCovered`; silently skipping one makes gaps look longer than they are. The unit's position never leaves the edge node: not a sync record, never logged, never published.
- **Supply chain:**
  - Never commit keys.
  - Every third-party binary is pinned in `deploy/tools.lock` with a locally computed sha256. Workflow actions are pinned by commit SHA in `release.yml` and the newer `ci.yml` jobs; pin any action you add or touch (the `python`, `web`, `infra`, `secrets` and `mbse` jobs and `harness.yml` still use version tags).
  - A VEX statement is written only for a finding a raw scan produced, with justification and checkable evidence.
- **Nothing from `../prep/` ever enters this repo.** Privateer products are mentioned only as integration targets, with the disclaimer in `docs/adapters/wayfinder.md`.

## Engineering rules (the maintainer's global rules)

- **TDD, strictly.** Write the test, run it, watch it fail for the right reason, then implement and prove it passes. Do not assume a change is correct.
- **SOLID, DRY, KISS, clean code.** Small functions with one job. Depend on protocols, not concrete classes: `bus.Bus`, `sync.records.ReferenceRecords`. No speculative abstraction.
- **Logging: stable messages, structured fields.** Use `log = get_logger(__name__)` from `sentinel.obs`, then write `log.info("Sync cycle failed", error=..., hub_id=...)`. Never interpolate values into the message; the message is the low-cardinality key you search and alert on.
- **Errors.** Handle them where they can be handled. Log them with context fields. Never swallow them silently.
- **Performance** only where measured; readability first.
