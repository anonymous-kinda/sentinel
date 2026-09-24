# Contributing to Sentinel

Sentinel is a decision aid whose value rests on one property: it fails honestly. The engine refuses rather than print a misleading number, a node degrades rather than fails, and every number traces to its inputs. The rules below exist to keep that true as the code changes.

Read these first:
1. `README.md`: what Sentinel is and what it claims.
2. `docs/technical-guide.md`: how the code is put together, how to run it, and recipes for extending it.
3. `docs/system-design.md`: the architecture decisions and what each rejected.
4. `CLAUDE.md`: the repository rules in their shortest form.

## The maintainer's rules

These are the maintainer's global rules, verbatim:

> - Use a TDD approach to solving problems. *Do not assume* that your solution is correct. Instead, *validate your solution is correct* by first creating a test case and running the test case to _prove_ the solution is working as intended.
> - **SOLID Principles**: Follow Single Responsibility, Open-Closed, Liskov Substitution, Interface Segregation, and Dependency Inversion principles for maintainable and extensible code.
> - **DRY (Don't Repeat Yourself)**: Avoid code duplication by extracting common logic into reusable functions, classes, or modules.
> - **KISS (Keep It Simple, Stupid)**: Strive for simplicity in design and implementation. Avoid over-engineering.
> - **Clean Code**: Write readable, self-documenting code with meaningful names, small functions, and clear structure.
> - **Error Handling**: Implement robust error handling and logging to aid debugging and maintain reliability. Use low-cardinality logging with stable message strings e.g. `logger.info{id, foo}, 'Msg'`, `logger.error({error}, 'Another msg')`, etc
> - **Performance**: Optimize for performance where necessary, but prioritize readability and maintainability.

How this repository applies them:

| Rule | In this repository | What holds you to it |
|---|---|---|
| TDD | Write the failing test, run it, and watch it fail for the right reason before writing the code. The risk engine was built down a six-rung ladder this way (`docs/risk-engine-design.md` section 7). A checker is also run against a deliberately broken input, so it cannot pass by accident (`tests/compliance/test_deploy_conformance.py`, `tests/docs/test_technical_guide.py`). Work that is not built yet is marked `@Planned` in `mbse/verification.sysml` and reported as unverified. | Review; `uv run pytest -q` must report 0 skipped |
| SOLID | Modules depend on protocols, not on each other: `Bus`, `ReferenceRecords`, `PassProvider`, `Router`, `Narrator`, `Clock`. New behaviour arrives as a new implementation plus one registration line (a provider factory, a `REGISTRARS` entry, a `CompositeRecords` prefix), not an edit to the core. Services receive what they use by injection, as `ToolRegistry` and `OpsService` do. | `.importlinter` contracts (`uv run lint-imports`); the provider conformance suite in `tests/conformance/` |
| DRY | One function admits every CDM, whatever its route (`ConjunctionService.ingest`). One script decides whether a bundle's signature is acceptable, for the installer, `make airgap-verify` and Ansible alike (`deploy/bundle/verify_signature.sh`). One file names every bus subject (`sentinel/bus/subjects.py`). One tool catalog serves the routers, the tools and the eval (`sentinel/ai/catalog.py`). | Review |
| KISS | SQLite, not a database server. Request/reply on NATS, not JetStream (ADR-004). Deterministic templates as the AI floor. No abstraction without a second implementation that needs it. | Review |
| Clean code | Units are suffixes in names. Error codes are stable strings. Functions are small; the engine's orchestration (`sentinel/risk/engine.py`) is separate from its maths. | `uv run ruff check .` |
| Error handling | Input that would make an answer wrong raises or is quarantined with a stable code; input that makes it incomplete degrades with a recorded warning. Nothing is swallowed: a catch-all logs with context and says why it exists. | Tests for every rejection code and refusal reason |
| Logging | `log = get_logger(__name__)` from `sentinel.obs`, then `log.info("Sync cycle failed", hub_id=hub_id, error=type(exc).__name__)`. The message is a constant: the low-cardinality key you search and alert on. Values go in fields. `SENTINEL_LOG_FORMAT=json` writes one JSON object per line. | `tests/test_logging_policy.py` parses `sentinel/`, `supplychain/`, `scripts/` and `compliance/` and fails on any non-constant message |
| Performance | Optimize where a measurement says so, and keep the measurement: `make bench-passes` for the pass engine, `docs/ddil-results.md` for the link. | The generated reports |

## Repository rules

These restate `CLAUDE.md`. If the two ever disagree, `CLAUDE.md` wins and this file needs fixing.

- **Units in names.** Every quantity carries its unit as a suffix: `_km`, `_km_s`, `_m`, `_m2`, `_m_s`, `_s`, `_deg`. A CDM carries kilometres for states and square metres for covariance; the engine converts on entry and works in metres.
- **Refusal instead of a wrong number.** `risk.assess()` never raises on bad data. It returns `Method.REFUSED` with a `RefusalReason` and records the value that tripped the gate. A Pc never travels without its `method`, and in the console a Pc renders only through `web/src/components/PcValue.tsx`. Never produce a Pc from element sets: demonstration mode gives geometry only (ADR-002).
- **Ingest policy.** Wrong input raises or is quarantined; incomplete input is accepted with a warning. Both are recorded. The same rule applies to CDMs (`sentinel/cdm/validate.py`), ephemerides (`sentinel/ephemeris/table.py`), element sets (`sentinel/passes/element_store.py`), units (`sentinel/passes/unit.py`) and the compliance sources (`compliance/sources.py`).
- **Logging.** Constant messages, values as fields (above). Never log a unit's position or any submitted coordinate.
- **Docs are checked against the repository.** `tests/test_docs.py` fails when `README.md`, `CLAUDE.md`, `SECURITY.md` or anything under `docs/` names a path, `make` target or `sentinel` subcommand that does not exist; `tests/docs/test_technical_guide.py` applies the same rules to this file. Every headline number quoted from a generated report or a test is registered in `tests/doc_claims.toml`. When a regenerated report moves a number, update the prose and the registry in the same commit.
- **Generated files.** Never hand-edit `docs/validation-report.md`, `docs/ddil-results.md`, `docs/ai-eval.md` (with `docs/img/ai-reliability.svg`), `docs/traceability.md`, `deploy/vex/sentinel.openvex.json` or the OSCAL documents under `compliance/oscal/`. Change the inputs and regenerate; `docs/technical-guide.md` lists each command. Commit a regenerated report in the same commit as the change that moved it.
- **Import contracts.** `.importlinter` enforces the module boundaries. The mission-agnostic core (`bus`, `triage`, `sync`, `crdt`, `ops`, `linkstate`) may not import a mission module (the conjunction module, the risk engine, the CDM codec, the pass module) or the API; the AI layer may not reach the maths; the pass module may not reach the network, sync or the API. `docs/technical-guide.md` quotes every contract. A new module gets its own contract, and a place in the core's forbidden lists, in the same commit.
- **The core stays closed to modules.** Adding or changing a mission module never edits `sentinel/sync`, `bus`, `crdt` or `triage`: that is the modular-open-systems claim. On such a branch, `git diff --stat main -- sentinel/sync sentinel/bus sentinel/crdt sentinel/triage` prints nothing; the pass module's proof is the empty range `67199b7..f16e294`. The core changes only deliberately: a bug fix proven by a failing test, typing with no behaviour change, or a design change recorded in an ADR.
- **Reference data costs link time.** Every record a hub offers over sync costs a round trip on a thin link. Read ADR-008, "Reference data on a thin link", before a hub offers edges anything more.
- **No network in tests.** Pytest runs with `--disable-socket --allow-unix-socket`. Use fixtures, recorded files and mock transports. `@pytest.mark.enable_socket` is only for a test that binds loopback ports. Skyfield uses its bundled timescale only.
- **Test data with provenance.** Expected values come from closed forms or from published sources, transcribed by hand with provenance and checksums (`fixtures/cara/PROVENANCE.md`). Never generate an expected value by running this code.
- **Data classes.** Every record is REAL, DERIVED or EXERCISE. Exercise data carries `ORIGINATOR=SENTINEL-EXERCISE`, and Sentinel's screening output `ORIGINATOR=SENTINEL-SCREENING`. Never present derived or exercise data as real.
- **Passes.** A gap is "not observed by catalogued imagers", never "safe" (`tests/passes/test_wording.py`). A provider raises `ImagerNotCovered` rather than skip an imager. The unit's position never leaves the edge node (ADR-010).
- **AI never computes.** The assistant routes to tools and phrases their facts. Every AI-written number must pass the grounding guard. Never publish a Jev number that did not come from a real run.
- **Traceability.** Requirement-to-evidence mapping lives in `mbse/verification.sysml`, not in pytest markers.
- **No secrets.** Never commit keys, tokens, `.env` files or inventories; `.gitignore` excludes the usual forms and the CI `secrets` job runs gitleaks over the full history. Hosted-AI keys come from the environment only.
- **Supply chain.** Every third-party binary is pinned in `deploy/tools.lock` with a locally computed sha256. Every workflow action is pinned by full commit SHA (`tests/test_workflows_pinned.py`). A VEX statement is written only for a finding a raw scan produced, with justification and checkable evidence.
- **Third-party products.** Privateer Space's products are named only as integration targets, with the no-endorsement disclaimer in `docs/adapters/wayfinder.md`.

## Commit style

Follow the history (`git log`):

- **Subject:** one line, sentence case, no trailing period, saying what changed. A milestone or area prefix is common when it helps: "M3: pass API per docs/icd/passes-api.md; element sets wired into every node", "Harness: OPSEC scenario - a unit set at the edge never reaches the hub (AC-4)".
- **Body:** what changed and why, in short paragraphs or bullets. Name the evidence: which tests prove it, which report it moved and by how much. Numbers come from a generated report or a test, never from memory.
- **One change per commit,** with its tests, its regenerated reports and its documentation.
- **Trailer:** commits written with an AI coding assistant end with a `Co-Authored-By:` line naming it, as the history shows.

## Before you open a pull request

Always:

```bash
uv run ruff check .
uv run lint-imports
uv run pytest -q          # must end "N passed", with nothing skipped
```

`make lint` runs the first two plus the TypeScript check, and `make test` runs pytest plus the web tests.

Then regenerate what your change feeds, and commit the output with the change. CI fails on a stale committed report, and `CLAUDE.md` holds the canonical version of this table:

| You changed | Run | It rewrites, or checks |
|---|---|---|
| `mbse/`, or a test or CI step the model cites | `make trace && make sysml-check` | `docs/traceability.md` |
| `compliance/sources/`, or evidence a control cites | `make compliance` (PyPI for trestle) | `compliance/oscal/` |
| `evals/`, or the routers in `sentinel/ai/` | `make ai-eval` | `docs/ai-eval.md`, `docs/img/ai-reliability.svg` |
| `sentinel/sync`, `harness/`, or anything else on the link | `make ddil` (the pinned `nats-server` and `toxiproxy`, a GitHub download) | `docs/ddil-results.md` |
| `sentinel/risk`, `fixtures/cara` | `make report` | `docs/validation-report.md` |
| Any document | `uv run pytest -q tests/test_docs.py tests/docs` | nothing: fails on a missing path, target or subcommand, or a registered number that moved |
| `web/` | `npm --prefix web run typecheck`, `npm --prefix web test`, `npm --prefix web run build` | nothing |
| `.github/workflows/`, `deploy/containers/Dockerfile` or deploy shell scripts | `make lint-release` (downloads the pinned linters from GitHub) | nothing |
| `deploy/bundle/` or packaging | `make airgap-selftest` and `make airgap-local` (downloads from GitHub and PyPI; needs `unshare -rn`) | nothing |

When a regenerated report moves a number the prose quotes, update the prose and `tests/doc_claims.toml` in the same commit.

## How CI is organised

Three workflows under `.github/workflows/`. Every action is pinned by commit SHA.

| Workflow | Runs on | Jobs |
|---|---|---|
| `ci.yml` | every push to `main` and every pull request | `python` (Python 3.11, 3.12 and 3.13: ruff, import contracts, the full pytest suite with network disabled, which includes the doc drift guards; the validation and AI-eval reports reproduced byte for byte); `web` (typecheck, vitest, build); `infra` (Terraform fmt and validate, Ansible syntax); `secrets` (gitleaks over the full history); `mbse` (the trace reproduced with no broken reference, SysML v2 syntax); `release-lint` (actionlint with shellcheck, hadolint, shellcheck); `supply-chain` (SBOMs, the vulnerability gate, the offline signature self-test, the Ansible signature gate); `compliance` (`make compliance`, uploading the OSCAL documents) |
| `harness.yml` | pull requests that touch `sentinel/sync`, `bus`, `crdt`, `ops`, `linkstate`, `passes`, `api`, `harness/` or `deploy/nats/`; nightly, with a 900 s denial; and on demand | one job per scenario: `denied`, `limited`, `intermittent`, `degraded`, `recovery`, `opsec`, each on real processes with the results uploaded |
| `release.yml` | a `v*` tag equal to `sentinel.__version__` | bundles for x86_64 and aarch64, SBOMs and the vulnerability gate; container images; keyless signing, SLSA provenance and SBOM attestations; offline verification and install on each architecture; SARIF upload; a draft release that a maintainer publishes |

The harness report (`docs/ddil-results.md`) is not regenerated in CI. It is committed from a local run of all six scenarios, and `make trace` reads it as evidence.
