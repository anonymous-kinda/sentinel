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
- `docs/validation-report.md` and `docs/ddil-results.md` are **generated files**. Regenerate them; never hand-edit.
- **Module boundaries are enforced by `.importlinter`**: `bus`, `sync`, `crdt` and `triage` may not import mission modules (`risk`, `cdm`, `passes`).
- **Data class on everything**: REAL, DERIVED or EXERCISE. Exercise data carries `ORIGINATOR=SENTINEL-EXERCISE`.
- **Nothing from `../prep/` ever enters this repo.** Privateer products are mentioned only as integration targets, with the disclaimer in `docs/adapters/wayfinder.md`.
