# Fixtures

Reference data the tests, the reports and a running node read. Every file
here was published by someone else or derived from published data by a
script named below, and each directory records its provenance and
checksums. Nothing is fetched at test time, and no expected value comes from
running Sentinel: a fixture built from Sentinel's own output would only
show that Sentinel agrees with itself.

An installed bundle ships this directory and points `SENTINEL_FIXTURES` at it.

| Path | What it is | Written by | Checked by |
|---|---|---|---|
| `fixtures/cara/` | NASA CARA's published test data, vendored byte for byte: the operational conjunction CDMs and their results spreadsheet, the Alfano and Omitron sample CDMs, and the MATLAB unit tests the expected values are quoted from. Provenance in `fixtures/cara/PROVENANCE.md`. A node also loads the operational CDMs as its reference library (`SENTINEL_LIBRARY`). | Copied from NASA's repository at a pinned commit | `fixtures/cara/SHA256SUMS`, verified by tier 3 |
| `fixtures/cara_cases.json` | The expected values tier 3 compares the engine with, transcribed from the files in `fixtures/cara/`. Each case records the NASA file and line it came from. | `uv run --with openpyxl python scripts/transcribe_cara_fixtures.py` | `tests/test_tier3_cara_validation.py`, which runs every case; `make report` writes the same comparison to `docs/validation-report.md` |
| `fixtures/omm/` | A public CelesTrak element-set snapshot (`fixtures/omm/celestrak-resource-20260924.json`), which a hub or standalone node and `sentinel screen` load by default. Element sets give pass timing and screening geometry, never a Pc (ADR-002). Provenance in `fixtures/omm/PROVENANCE.md`. | `scripts/fetch_omm.py` (network; writes a new dated file, refreshed deliberately) | `fixtures/omm/SHA256SUMS` |
| `fixtures/wayfinder/` | An assumed-schema payload for the Wayfinder adapter's contract test. **It is not Wayfinder output**: its shape is the one `sentinel/adapters/wayfinder.py` assumes, and its positions are the public WORLDVIEW-3 element set propagated by SGP4. See `fixtures/wayfinder/PROVENANCE.md` and the disclaimer in `docs/adapters/wayfinder.md`. | `make wayfinder-fixture` (offline, deterministic) | `tests/adapters/test_wayfinder.py`, which re-derives every position |

The test suite runs tier 3 in full: `uv run pytest -q` must report 0 skipped.
The case format is written by `scripts/transcribe_cara_fixtures.py` and read by
`sentinel/validation/cara.py`, which the tests and `make report` share.
