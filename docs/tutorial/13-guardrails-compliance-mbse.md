# 13. Keeping it honest: guardrails, compliance and the trace

## What you will learn

- How the test suite is laid out as a ladder, what each kind of test proves (tiers, property, conformance, API, hostile input), and how `pytest-socket` keeps it off the network.
- How a known bug is recorded as a strict xfail, and why the suite then fails on the day the bug is fixed.
- How `.importlinter` contracts and mypy turn architecture and types into checks that fail.
- How the doc guards hold prose to the repository: paths, commands and every quoted number.
- How the OSCAL package and the SysML trace turn test evidence into control and requirement status, and which check fails when a doc, a boundary or a requirement drifts.

## Why it exists

Sentinel's claims are only as good as their evidence. "Every number traces to its inputs" and "the engine refuses rather than misleads" are statements a reviewer should be able to check, not take on trust. Evidence rots quietly, too. A test is renamed, and a requirement that cited it still reads "verified". A report is regenerated, and the README keeps quoting last month's number. An SSP says a control is implemented, but the check behind it was deleted.

This chapter covers the machinery that makes each of those drifts fail something. It serves two readers. An engineer changing the code learns within minutes which promise a change broke. An assessor gets a system security plan, a POA&M and a requirement trace that are generated from what actually ran, so they cannot quietly disagree with the code.

One idea runs through all of it: **a check is itself tested against a deliberately broken input before it is trusted.** A green run then means the rule was applied, not skipped.

## Concepts

### Authored inputs, checks, generated outputs

Everything in this chapter follows one pattern. People write the inputs, a script generates the outputs, and a check fails when the committed output is not what the inputs generate.

```
authored                      generator                       generated, never hand-edited
─────────────────────────     ────────────────────────────    ──────────────────────────────
mbse/*.sysml               ─> scripts/trace.py (make trace) ─> docs/traceability.md
compliance/sources/*.toml  ─> scripts/oscal_evidence.py    ─> compliance/oscal/**
  + pytest JUnit XML            (make compliance)
sentinel/risk, fixtures/   ─> scripts/validation_report.py ─> docs/validation-report.md
harness runs (6 scenarios) ─> python -m harness.report     ─> docs/ddil-results.md
evals/, the AI routers     ─> scripts/ai_eval.py           ─> docs/ai-eval.md
sentinel/api routes        ─> scripts/export_openapi.py    ─> docs/icd/openapi.json
deploy/vex/statements.toml ─> make vex                     ─> deploy/vex/sentinel.openvex.json

README.md, docs/**         ─> tests/test_docs.py + tests/doc_claims.toml: quoted numbers
                              must match the generated reports above
```

A hand edit to a generated file is not a shortcut. The next regeneration overwrites it, and a check compares the committed file with a fresh one before that happens.

### "The evidence exists" is not "the evidence passed"

Two different questions get asked of every citation:

- **Does it resolve?** Is there a test with that node id, a CI job or step with that name, a harness scenario with that name? This is fast and deterministic, and `make trace` and the OSCAL generator ask it on every run. (The trace is a little stricter about scenarios: it wants one marked PASS in the recorded DDIL report.)
- **Did it pass?** Only a run can say. CI runs the tests. The OSCAL assessment results read this run's JUnit XML and record each citation as passed, failed, missing or not supplied.

The requirement trace answers only the first question. "Verified" in `docs/traceability.md` means every piece of evidence a requirement's verification cases name exists. It does not mean a CI job has run: no CI job has run on a hosted runner yet (chapter 12).

### Strict xfail

`@pytest.mark.xfail(strict=True, reason=...)` says: this test is expected to fail, because of a known bug. The suite stays green while the bug exists, and the reason appears in every run's summary. With `strict=True`, a test that unexpectedly passes is reported as `XPASS(strict)` and counts as a **failure**. So the day someone fixes the bug, the suite goes red until they remove the marker, and the record cannot go stale. A skip would hide the bug. Deleting the test would lose it.

### Forbidden imports

An import-linter "forbidden" contract says: modules under these packages may not import those modules, directly or through a chain of imports. Architecture drawn in a diagram is a wish. The same boundary written as a contract fails CI when someone crosses it.

### OSCAL in one paragraph

OSCAL is NIST's machine-readable format for security documentation. A **catalog** is the full control set (NIST SP 800-53 Rev 5). A **profile** selects and tailors controls from it. A **component definition** says what each part of a system does for each control. The **system security plan (SSP)** puts that together for one system. An **assessment plan** says how controls will be checked. **Assessment results** record what a check found, and the **POA&M** (plan of action and milestones) lists every weakness with its plan. `compliance-trestle` validates the documents against the OSCAL schemas.

### SysML v2 in one paragraph

SysML is the systems-engineering modelling language. Version 2 has a textual notation. Sentinel's model uses four constructs: `requirement` (with an id such as `REQ-DEP-002` and a text), `part` (the system's structure), `satisfy R by P` (this part meets this requirement), and `verification` cases whose metadata names the evidence. `@Evidence` names one artifact. `@Planned` marks evidence that is not built yet.

```
requirement REQ-AI-002  <── satisfy ── part sentinel.edge.assistant.groundingGuard
       ▲
       └── verify ── verification VC-AI-002
                        @Evidence pytest   tests/ai/test_grounding.py::test_an_invented_number_is_caught
                        @Evidence pytest   ...
```

## Code walkthrough

### 1. The test ladder: `tests/` and `pyproject.toml`

The risk engine was built rung by rung, each test written and seen to fail before the code that passes it. The ladder is in `docs/risk-engine-design.md`, section 7, and the tiers map to files and pytest markers (`tier1` to `tier6` in `pyproject.toml`):

```
tier1  tests/test_tier1_geometry.py         frames and the encounter plane; no probability yet
tier2  tests/test_tier2_integration.py      the 2D integral vs closed forms and a scipy dblquad oracle
tier3  tests/test_tier3_cara_validation.py  NASA CARA's published cases, vendored unmodified, sha256-checked
tier4  tests/test_tier4_dilution.py         maximum Pc and the dilution flag, anchored to asymptotics
tier5  tests/test_tier5_refusal.py          the refusal gates: each says which condition tripped, at what value
tier6  tests/test_tier6_contract.py         the output contract: no Pc without its method
```

The rule that matters most is in the tier 2 docstring. No expected value may be copied from an earlier run of this code, because that only proves the code agrees with itself. Expectations come from closed forms, an independent oracle, or NASA's published values ([ADR-003](../system-design.md#adr-003--reimplement-foster-estes-2d-pc-in-python-nasa-caras-published-cases-as-the-oracle)). `tests/conftest.py` provides `nominal_conjunction`, built with `make_conjunction` from `sentinel/risk/synthetic.py`.

The other kinds of test, and what each proves:

- **Property tests.** `tests/property/test_crdt.py` drives three replicas with Hypothesis's `RuleBasedStateMachine` through random writes and a network that drops, duplicates and reorders messages. It checks convergence, no loss, no silent overwrite, and that conflicts stay visible. It finds orderings nobody would think to write by hand.
- **Conformance tests.** `tests/conformance/test_pass_providers.py` runs every pass provider in `PROVIDER_FACTORIES` against one contract and a brute-force Skyfield oracle. Adding a provider is one line, and it is then held to everything the others are ([ADR-011](../system-design.md#adr-011--two-pass-providers-behind-one-contract-held-to-one-conformance-suite)).
- **API tests.** `tests/api/` drives the FastAPI app through its test client: routes, status codes, the SSE stream, the Content-Security-Policy.
- **Hostile-input tests.** `tests/test_ingest_hostile.py` (malformed CDMs at the ingest seam: nothing raises, nothing poisons the store), `tests/sync/test_hostile_hub.py` (a hub that lies in its replies) and `tests/test_ops_hostile_peer.py` (a peer that forges or erases operator data).
- **Policy tests.** These parse source rather than trusting review. `tests/test_logging_policy.py`, for example, fails any log call whose message is an f-string, a format or a variable.

`pyproject.toml` sets `addopts = "--disable-socket --allow-unix-socket"`. `pytest-socket` replaces Python's socket functions for the test process, so any attempt to open an internet socket raises `SocketBlockedError`.

**Easy to get wrong:** `pytest-socket` guards only the test process. A test that runs a subprocess (`tests/supplychain/test_install_integrity.py` runs the real `install.sh`) is offline because it uses stubs, not because pytest-socket reaches it. Also, "0 skipped" is a rule, not a check. CI runs `pytest -q -rs`, which lists skips but does not fail on them. What does catch a skip is the compliance evidence: a skipped test that a control cites is recorded as *missing* (section 7).

### 2. Strict xfails: recorded bugs

`tests/test_ops_hostile_peer.py::test_an_untrusted_peer_cannot_erase_an_annotation` is a strict xfail. Its reason records a design gap: ADR-005 signs the decision log but not annotations, so a peer that can reach the exchange subject can erase an annotation. Right below it, `test_mvmap_keeps_what_the_peer_never_saw` is its control: the same merge with an honest context erases nothing. `tests/sync/test_hostile_hub.py` states the convention in its docstring: a bug found in the closed core is recorded as a strict xfail until it is fixed.

**Easy to get wrong:** a plain `xfail` (not strict) lets a fixed bug pass silently as `XPASS`. The marker then outlives the bug, and the reason in the summary becomes a false statement. Pair every xfail with a control test, so the xfail can only be failing for the reason it names.

### 3. Architecture as a check: `.importlinter`

`.importlinter` sets `root_package = sentinel` and `include_external_packages = True`, so third-party packages (numpy, scipy, fastapi, nats) can be forbidden too. The contracts that carry the design:

| Contract | Says |
|---|---|
| `risk-pure` | the engine does no I/O: no fastapi, nats, sqlite3 or httpx |
| `core-is-mission-agnostic`, `sync-is-mission-agnostic` | bus, triage, sync, crdt, ops and linkstate import no mission module and not the API |
| `cdm-is-a-seam` | the CDM codec depends on nothing above it |
| `ai-does-no-math`, `hosted-ai-at-the-edges` | the AI layer cannot reach risk, cdm, numpy or scipy; hosted SDKs stay in their adapters |
| `passes-is-independent`, `passes-offline` | the pass module knows nothing of risk, sync or the API, and has no network stack |
| `screening-never-decides-pc` | screening produces geometry; only the engine decides a Pc |

The ephemeris contract lists one permitted exception under `ignore_imports`, with a comment saying why: the CCSDS time-code parser that every CCSDS message shares.

**Easy to get wrong:** contracts are transitive. If an AI module imports `sentinel.risk.engine`, import-linter reports the direct edge, and also every chain that reaches numpy or scipy through it. The contracts are also cited as evidence in the SysML model: VC-AI-001 names `ai-does-no-math` (section 8). Renaming a contract id breaks the trace, not just the linter.

### 4. Types as a check: `make typecheck` and `tests/test_typecheck.py`

`make typecheck` runs `mypy sentinel`. `pyproject.toml` gives the core (`sentinel.bus`, `crdt`, `sync`, `triage`) and `sentinel.risk` every flag `mypy --strict` turns on, listed one by one. The rest of `sentinel/` gets mypy's standard checks. A TODO list of modules has `ignore_errors = true` while their typing is fixed. Modules leave that list, and nothing new joins it.

**Easy to get wrong:** a per-module `strict = true` would switch strict mode on for *every* module, so the flags have to be listed. That list can drift from what `--strict` means in the installed mypy. `tests/test_typecheck.py` closes the gap. `strict_flags` asks mypy itself which options `--strict` changes, and `loose` reads the options mypy derives for each module from `pyproject.toml`. A strict module missing a flag fails, and so does strictness leaking onto the rest.

### 5. The doc guards: `tests/doclint.py`, `tests/test_docs.py`, `tests/doc_claims.toml`, `tests/docs/`

`tests/doclint.py` holds the rules, and `tests/test_docs.py` applies them to `README.md`, `CLAUDE.md`, `SECURITY.md`, `fixtures/README.md` and every Markdown file under `docs/`, this tutorial included.

- `parse_markdown` splits a document into code (inline spans and fenced lines) and links.
- `missing_paths` treats a word in code as a repository path when it contains `/` and starts with a top-level directory. It skips placeholders (`<ver>`, `$VAR`) and local-only outputs (`build/`, `dist/`, `harness/results/`, `web/dist/`). A pytest node id names its file.
- `commands`, `unknown_make_targets` and `unknown_cli_commands` check every `make` target against the Makefile, and every `sentinel` subcommand against the real argparse tree (`cli_tree`), not against `--help` text.
- `scripts_outside_the_project` flags a repository script run with the system Python instead of through `uv run python`. On a fresh clone the system Python has none of the project's dependencies, so the documented command would fail.
- `undocumented_packages` requires a docstring in every package under `sentinel/`.
- `claim_problems` checks a registered claim. The quoted prose must still be in the document, every pattern must still be in the generated source, and every number in the quote must match a number in the patterns, at the precision the prose states. That last check calls `check_grounding` from `sentinel/ai/grounding.py`: the same rule that stops the AI assistant from inventing a number stops the README from quoting a stale one ([ADR-007](../system-design.md#adr-007--ai-that-cannot-corrupt-the-decision-jev-routes-code-computes-claude-phrases-the-operator-decides)).

`tests/doc_claims.toml` is the registry. Each `[[claim]]` names an `id`, the `doc` that quotes it, the `quoted` text, the generated `source`, and `patterns` that must appear there. When a regenerated report moves a number, the claim fails. You update the pattern, then the prose, then the quote.

The first half of `tests/test_docs.py` runs each rule on a miniature repository with a deliberate fault (a missing path, a bad target, a stale number) and asserts the rule reports exactly that fault. Only then does the second half apply the rules to the real documents.

`tests/docs/` adds checks that need more than Markdown:

- `test_program_docs.py`, through `tests/docs/doccheck.py`, covers the white paper, quad chart, demo script and install guide: the quad chart's SVG text, make variables, test functions they name, whole `sentinel` command lines, and every proof-point number registered.
- `test_value_first.py` checks that every ADR opens with **Buys.** and **Costs.**, that the README states its limits straight after its value, and that the index says who reads what.
- `test_tutorial.py` checks that every chapter the overview lists exists, and that every written chapter has the nine sections in order.
- The ICD tests (`test_openapi_current.py`, `test_asyncapi.py`, `test_cdm_profile.py`, `test_sync_envelope.py` and others) hold each interface document to the code, both ways.
- `test_technical_guide.py` holds the technical guide, the index and `CONTRIBUTING.md` to the configuration the code reads.

**Easy to get wrong:** the path check reads every word in code. Writing about a file that no longer exists, even to say it was renamed, fails the guard. Describe it in prose, or name the new path.

### 6. Generated reports, and how each is held

| Output | Generator | What fails when the committed copy is stale |
|---|---|---|
| `docs/traceability.md` | `make trace` | `tests/mbse/test_real_model.py::test_the_committed_trace_is_current`; CI `mbse` runs `git diff --exit-code` |
| `compliance/oscal/` (authored four) | `scripts/oscal_evidence.py` | `tests/compliance/test_package_integrity.py::test_committed_documents_are_what_the_sources_generate` |
| `docs/validation-report.md` | `make report` | CI `python` job: regenerate, then `git diff --exit-code` |
| `docs/ai-eval.md` | `make ai-eval` | CI `python` job, the same way |
| `docs/icd/openapi.json` | `make openapi` | `tests/docs/test_openapi_current.py` |
| `deploy/vex/sentinel.openvex.json` | `make vex` | `make scan` (`--check`) |
| `docs/ddil-results.md` | `make ddil` | `harness.report` refuses a partial set (`tests/test_harness_report.py`); the claims registry holds the prose to it |

`docs/ddil-results.md` is the one report CI cannot regenerate, because it needs a real two-node cluster. It is the recorded run, and it says so in its header. The assessment results and POA&M are special in a different way. They carry the run's timestamps, so every `make compliance` changes them. The committed copies are the snapshot from the last local run, and CI's copies describe each commit.

### 7. The OSCAL package: `compliance/`

Three authored files hold every decision:

- `compliance/sources/controls.toml`: for each selected control, why it was selected, and for each component, a statement, a status (`implemented`, `partial`, `planned`), evidence (`tests`, `harness`, `ci`, `files`) and a plan.
- `compliance/sources/system.toml`: the system description, boundary, provisional categorization, components, users and assessment methods.
- `compliance/sources/stig.toml`: every STIG rule decision: applied, deviation (with justification, mitigation and plan), or not applicable.

The generator's modules, in the order data flows through them:

- `compliance/sources.py`: `load_sources` and `_contribution` enforce the rules at load time. `implemented` needs automated evidence (tests, a harness scenario or a CI job, since a file alone shows intent). Anything less needs a plan. Unknown keys and malformed citations are errors.
- `compliance/citations.py`: `unresolved` checks that every cited file exists, every test resolves, every CI job exists in its workflow, and every harness scenario is in `harness/scenarios.py`. It also refuses a `planned_evidence` path that already exists, because the statement should now cite it. Tests are resolved **statically**, by parsing the test file's AST (`_module_names`), so this runs in milliseconds with no collection.
- `compliance/inputs.py`: `read_junit`, `read_harness` and `read_xccdf` parse the three kinds of evidence. Unparseable XML, a run with no timestamp or no UTC offset, or an unknown result value raises `EvidenceError`.
- `compliance/evidence.py`: `cites` matches a node id to JUnit cases, parametrised ones included. `_test_result` gives each citation one of four states: `passed`, `failed`, `missing` (matched nothing, or only skips) or `not-supplied` (harness results not given to this run).
- `compliance/authored.py` builds the profile, component definition, SSP and assessment plan from the sources alone. `compliance/assessment.py` builds the assessment results (one observation per control with evidence, and a finding for each control not satisfied) and the POA&M. The POA&M gets an item for every failing test, every missing citation, every failed harness scenario, the STIG scan results (or one item saying there are none), every partial or planned contribution, and every STIG deviation.
- `compliance/cli.py`: `main` returns 2 on `SourceError` or `EvidenceError` and writes nothing trustworthy. Failing tests do **not** fail the generator: they are what the POA&M is for.

`make compliance` runs, in order: verify and import the vendored NIST catalog; write the four authored documents; run the whole suite with `--junitxml`; generate the assessment results and POA&M; `trestle validate -a`; and only then fail if pytest failed. **Easy to get wrong** is that order. The suite checks that the committed SSP is what the sources generate, so if pytest ran before the authored documents were rewritten, every source edit would fail its own first run and file the staleness as a POA&M item. `tests/compliance/test_make_compliance.py` holds the order by reading `make -n compliance`.

The STIG side: `deploy/ansible/roles/stig/` applies the decided subset, and `tests/compliance/test_stig_role.py` checks every rule id it names against the vendored DISA XCCDF and the decisions. It also compares the SSH algorithms, audit rules, banner and acknowledgement script with DISA's text. With `stig_scan: true`, the role's `tasks/scan.yml` runs OpenSCAP, fetches the XCCDF results, and converts them to a DISA `.ckl` checklist with the MITRE SAF CLI. `make compliance XCCDF=...` then sorts each scanned rule into the POA&M. The role and its scan have not run against a host.

**No ATO is claimed**, and tests hold that line. `test_no_authorization_is_claimed` requires the SSP to carry no authorization date, a state other than operational, and the sentence that no authorization was sought or granted. `test_committed_poam_never_approves_a_deviation` allows only `open` and `deviation-requested` risk states. The package is ATO-ready evidence, not an authorization ([docs/compliance.md](../compliance.md)).

### 8. The trace: `mbse/`

`mbse/requirements.sysml` holds the requirements, `mbse/sentinel.sysml` the parts and the `satisfy` relations, and `mbse/verification.sysml` one verification case per requirement.

- `mbse/sysml.py`: `read_model_dir` is a reader for the subset the trace needs, not a full parser. It lexes, groups statements into blocks, and interprets requirements, satisfy relations and verification cases with their `@Evidence` and `@Planned` metadata. Anything it cannot read faithfully raises `ModelError` with the file and line, rather than tracing part of the model.
- `mbse/evidence.py`: one index per kind of evidence, each answering "does this locator resolve?" `PytestIds` reads `pytest --collect-only -q` output. `HarnessScenarios` reads the PASS rows of `docs/ddil-results.md`. `ImportContracts` reads contract ids from `.importlinter`. `CiSteps` reads step names and job ids from `.github/workflows/ci.yml`. A new kind of evidence is a new index, and the trace does not change.
- `mbse/trace.py`: `build_trace` joins them. `_status` is conservative: **broken-reference** if any case is broken; **unverified** if there is no case or any case is `@Planned`; **verified** only otherwise. A satisfy relation that names an unknown part, or a case that verifies nothing, is a problem too. `render_markdown` writes the report, with a "Planned evidence" table when any case is planned.
- `mbse/generate.py`: `main` collects pytest ids in a subprocess, builds the trace, and **always writes** `docs/traceability.md`, problems included. It exits 0 when clean, 1 when there are problems, and 2 when the model is unreadable or collection failed. It logs a warning when a planned case's evidence now exists.
- `mbse/syntax.py` with `scripts/sysml_check.py` (`make sysml-check`): parses each file with the SysML v2 pilot grammar through sysml2py, in an isolated environment. It first requires the parser to reject `KNOWN_BAD`, a model missing a semicolon, because a validator that accepts that has checked nothing. It checks syntax only, not names or types.

**Easy to get wrong:** `@Planned` is the only way to state future work, and it always reads as unverified, never verified. Two more subtleties. The trace and the OSCAL citations resolve tests differently: the trace uses real collection, the OSCAL generator uses the AST. A test file that exists but cannot be collected (an import error at module level) stops the trace, because collection fails and `scripts/trace.py` exits 2, while the OSCAL citations still resolve; the test run then catches it. And the `ci` index reads only `ci.yml`, so a step in `harness.yml` or `release.yml` cannot be cited as trace evidence.

## Try it

Every command here was run while this chapter was written. Commands that break something are followed by the `git restore` that undoes them. Start from a clean working tree (`git status --short` prints nothing).

**The ladder, one rung at a time, then the whole suite:**

```bash
uv run pytest -q -m tier5
uv run pytest -q -rx
```

The first runs only the refusal gates, selected by marker. The second runs everything. Look for a final line with a `passed` count, an `xfailed` count and no `skipped` count (pytest leaves out a count that is zero), and an `XFAIL` line in the summary for each recorded bug, with its reason.

**The network is off inside tests:**

```bash
mkdir -p build/try && cat > build/try/test_network.py <<'EOF'
import urllib.request


def test_reaches_the_internet():
    urllib.request.urlopen("https://example.org", timeout=2)
EOF
uv run pytest -q build/try/test_network.py
```

It fails with `SocketBlockedError: A test tried to use socket.getaddrinfo.` The DNS lookup is refused before any packet leaves.

**A strict xfail fails once the bug is fixed:**

```bash
cat > build/try/test_strict_xfail.py <<'EOF'
import pytest


@pytest.mark.xfail(strict=True, reason="recorded bug: totals are off by one")
def test_the_total_is_right():
    assert 1 + 1 == 2  # the "bug" is already fixed
EOF
uv run pytest -q build/try/test_strict_xfail.py
uv run pytest -q -rx tests/test_ops_hostile_peer.py
```

The first reports `FAILED ... [XPASS(strict)]`. The second shows a real recorded bug, reported as `XFAIL` with its reason, alongside its passing control test.

**Boundaries and types:**

```bash
uv run lint-imports
make typecheck
```

Look for every contract `KEPT` and a final count with 0 broken, then mypy's `Success: no issues found`. mypy's `annotation-unchecked` notes come from standard-mode modules and are not errors.

**The trace and the model's syntax:**

```bash
make trace
git status --short docs/traceability.md
make sysml-check
```

`make trace` logs `Trace written` with the counts of verified, unverified and broken requirements (the numbers are in `docs/traceability.md`). `git status` prints nothing, because the committed trace is current. `make sysml-check` logs `SysML syntax checked` with `errors=0` and the validator's version. It downloads sysml2py into uv's cache the first time; after that, `UV_OFFLINE=1 make sysml-check` works with no network.

**The doc guards:**

```bash
uv run pytest -q tests/test_docs.py tests/docs
```

Every test passes. Test ids name the document they checked, so `-v` shows each file under guard, this chapter included.

**The OSCAL package:**

```bash
uv run python scripts/oscal_evidence.py
git status --short compliance/oscal
uv run python -c "import json; p = json.load(open('compliance/oscal/plan-of-action-and-milestones/sentinel/plan-of-action-and-milestones.json'))['plan-of-action-and-milestones']; [print('-', i['title']) for i in p['poam-items']]"
uv run python -c "import json; s = json.load(open('compliance/oscal/system-security-plans/sentinel/system-security-plan.json')); print(s['system-security-plan']['system-characteristics']['status'])"
```

The generator logs `Authored documents written`, and `git status` shows nothing, because they were current. The POA&M's first item says the host STIG baseline has not been verified by a scan. After it come the partial and planned contributions, each named by control and component, and then the STIG deviations. The SSP's status is `under-development`, and its remarks say no authorization was sought or granted.

The full pipeline is `make compliance`. It runs the whole suite, then logs `Assessment documents written` with the number of controls observed and satisfied, the findings and the POA&M items. Then `trestle validate -a` prints `VALID` for every document. It rewrites the assessment results and POA&M with this run's timestamps, so run `git restore compliance/oscal` afterwards unless you mean to commit a new snapshot.

### Break it on purpose

**Rename a cited test.** `tests/ai/test_grounding.py::test_an_invented_number_is_caught` is cited three times: by the SysML model (VC-AI-002), by the SSP (SI-15), and by the white paper.

```bash
sed -i 's/def test_an_invented_number_is_caught/def test_an_invented_number_is_flagged/' tests/ai/test_grounding.py
make trace
uv run python scripts/oscal_evidence.py
uv run pytest -q tests/mbse/test_real_model.py tests/compliance/test_package_integrity.py tests/docs/test_program_docs.py
git restore tests/ai/test_grounding.py docs/traceability.md
```

What catches it:

- `make trace` logs `Trace problem` with `VC-AI-002: pytest evidence '...::test_an_invented_number_is_caught' does not exist`, and make fails. The rewritten `docs/traceability.md` now shows `broken-reference` for REQ-AI-002 and a Problems section. In CI, `git diff --exit-code` would fail on it as well.
- The OSCAL generator logs `Compliance generation failed` with `citations do not resolve: si-15: ... is not defined`, exits 2, and writes nothing.
- Three tests fail: `test_the_model_has_no_broken_references`, `test_every_citation_resolves`, and the program-docs check that every test function the white paper names exists.
- `tests/test_docs.py` does not catch the rename itself: its path check reduces the node id to `tests/ai/test_grounding.py`, which still exists. Once `make trace` has rewritten the report, though, the claims that quote the trace's counts fail: `readme-trace-counts`, `wp-trace-summary` and the two quad-chart claims. The README, the white paper and the quad chart would otherwise go on saying every requirement is verified.

**Mark a verified case as planned.** Add `@Planned` to VC-DEP-004, the Content-Security-Policy case:

```bash
sed -i '/verify consoleNeverCallsOut;/a\        @Planned { milestone = "M7"; reason = "tutorial demonstration"; }' mbse/verification.sysml
make trace
uv run pytest -q tests/test_docs.py -k readme-trace-counts
git restore mbse/verification.sysml docs/traceability.md
```

`make trace` succeeds, because a planned case is legitimate. It reports one requirement unverified, adds a "Planned evidence" table naming VC-DEP-004, M7 and the reason, and warns `Planned evidence now exists`, since the cited test is still there. What fails is the claims registry. The README quotes the trace's counts, and `readme-trace-counts` now fails with `docs/traceability.md no longer says '| **total** | ...'`: the generated source moved under the prose. A requirement cannot quietly drop from verified to unverified while the README says otherwise.

**Cross a boundary.** Give the AI layer a path to the maths:

```bash
echo "import sentinel.risk.engine" >> sentinel/ai/policy.py
uv run lint-imports
git restore sentinel/ai/policy.py
```

"The AI layer has no path to the maths" is reported `BROKEN`. The listing shows `sentinel.ai.policy -> sentinel.risk.engine`, plus the chains through it to numpy and to scipy.

**Drop a type annotation, in the core and outside it:**

```bash
printf '\n\ndef scratch_helper(x):\n    return x\n' | tee -a sentinel/triage/__init__.py >> sentinel/screening/report.py
make typecheck
git restore sentinel/triage/__init__.py sentinel/screening/report.py
```

mypy reports one error, `Function is missing a type annotation [no-untyped-def]`, in `sentinel/triage/__init__.py` only. The same function in the screening module passes, because screening gets standard checks.

**Move a quoted number:**

```bash
sed -i 's/[0-9]\+ requirements: [0-9]\+ verified/0 requirements: 0 verified/' README.md
uv run pytest -q tests/test_docs.py -k readme-trace-counts
git restore README.md
```

The claim fails with `README.md no longer says '...'`, quoting the registered sentence with the trace's real counts. The prose, the registry and the generated trace have to agree.

End with `git status --short`, which should print nothing.

## Design choices

**Expected values from outside the code.** The ladder takes its expectations from closed forms, an independent oracle and NASA's published cases, never from a previous run. That buys trust in every number: the tests can catch a wrong answer, not just a changed one. It costs hand transcription of the CARA fixtures and some events with no answer, because the engine refuses them. Rejected: snapshot tests of engine output, and Orekit as an oracle. [ADR-003](../system-design.md#adr-003--reimplement-foster-estes-2d-pc-in-python-nasa-caras-published-cases-as-the-oracle).

**Boundaries enforced by import contracts in one process.** This buys a modular architecture that ships as one bundle, with boundaries that fail CI instead of relying on review. It costs a contract file to maintain, and exceptions that must be written down (`ignore_imports`). Rejected: separate services to force the boundaries, which a disconnected edge cannot afford. [ADR-004](../system-design.md#adr-004--modular-monolith-with-an-internal-event-bus); the AI contract is [ADR-007](../system-design.md#adr-007--ai-that-cannot-corrupt-the-decision-jev-routes-code-computes-claude-phrases-the-operator-decides).

**Strict typing where a wrong type is costly.** The core carries data between nodes and the engine computes the numbers, so both get `--strict`. That buys the strongest checks where a bug crosses a link or changes a Pc. It costs slower changes there, and a TODO list of modules that do not yet pass standard mypy. Rejected: strict everywhere at once, which would have stalled active work. This rule is in the repository's `CLAUDE.md`; no ADR records it.

**Quoted numbers checked by the AI's grounding rule.** One function decides whether a number is supported by its evidence, for the assistant and for the docs. That buys consistency: a claim fails at the precision it states. It costs a registry entry for every headline number, and an update to the pattern, the prose and the quote whenever a report moves. The alternatives were to generate the prose from the reports, or to check nothing and let the README drift. No ADR records this choice; the header of `tests/doc_claims.toml` states the rule, and the grounding function is [ADR-007](../system-design.md#adr-007--ai-that-cannot-corrupt-the-decision-jev-routes-code-computes-claude-phrases-the-operator-decides).

**Requirement evidence in the SysML model, not in pytest markers.** The model is the MBSE artifact a systems engineer reads, and the trace is generated from it. That buys one source of truth that can also cite contracts, CI steps and harness scenarios, which markers cannot. It costs a custom reader for a subset of SysML, plus a separate syntax check that covers syntax only. No pytest marker carries the mapping, which lives in `mbse/verification.sysml`, and `tests/test_pytest_markers.py` fails on any marker `pyproject.toml` declares that no test uses. See [docs/traceability.md](../traceability.md).

**An SSP generated from sources and evidence, not written as a document.** That buys statements that cannot claim what the evidence does not show: `implemented` needs automated evidence, a dangling citation stops generation, and a missing test opens a POA&M item. It costs a generator to maintain, and it can say only what a check can check. Organizational controls stay planned against a `program` component. The alternative, a hand-written SSP, drifts from the code as soon as either one changes. See [docs/compliance.md](../compliance.md). The supply-chain controls it cites are [ADR-012](../system-design.md#adr-012--keyless-signing-verified-offline-against-a-pinned-trust-root).

**Existence in the trace, results in the assessment.** The trace checks that evidence exists, so it is fast, deterministic and cannot flake. The OSCAL assessment reads pass or fail from an actual run. That split buys a trace you can regenerate in seconds on any machine. It costs a "verified" that means less than it sounds, so the legend in `docs/traceability.md` says exactly what it means.

## How it fails

| Drift | What catches it | What you see |
|---|---|---|
| A test the model cites is renamed or deleted | `make trace`; `tests/mbse/test_real_model.py`; CI `mbse` | `Trace problem ... does not exist`; `broken-reference` in the report; exit 1 |
| A test the SSP cites is renamed | `scripts/oscal_evidence.py`; `test_every_citation_resolves` | `Compliance generation failed ... citations do not resolve`; exit 2; nothing written |
| A cited test is skipped or not run | `make compliance` | The citation is `missing`; the control is not satisfied; a POA&M item "cites evidence missing from the run" |
| A cited test fails | `make compliance` | A finding in the assessment results and a POA&M item; the target fails after writing them |
| `implemented` without automated evidence | `load_sources` | `implemented needs automated evidence (tests, harness or ci)` |
| A generated document edited by hand | The currency test for that output | `... is stale or was edited by hand: run make compliance`, or `docs/traceability.md is stale: run make trace` |
| An unreadable SysML model | `read_model_dir` | `ModelError` naming file and line; `scripts/trace.py` exits 2 |
| A validator that accepts anything | `mbse/syntax.py` | `SysML validator not trusted`; exit 2 |
| A module crosses a boundary | `uv run lint-imports`; CI `python` | The contract reported `BROKEN`, with every import chain |
| Strict typing lost on a core module | `tests/test_typecheck.py` | The module named, with the strict flags it no longer gets |
| A doc names a missing path, target or subcommand | `tests/test_docs.py` | The document's id and the missing names |
| A report moves a quoted number | `tests/test_docs.py` claims | `<doc> no longer says ...` or `<source> no longer says ...` |
| A fixed bug still marked xfail | pytest | `[XPASS(strict)]`, counted as a failure |
| A test opens a network socket | `pytest-socket` | `SocketBlockedError` |
| A deviation marked approved | `test_committed_poam_never_approves_a_deviation` | The unexpected risk status |

## Check yourself

1. You rename a test that the SysML model, the SSP and the white paper all cite. Which checks fail, and which obvious-looking check does not?

<details><summary>Answer</summary>

`make trace` (a broken reference, and `tests/mbse/test_real_model.py`), the OSCAL generator and `test_every_citation_resolves`, and the program-docs check on test functions the white paper names. In CI, the regenerated trace would also differ from the committed one. The path check in `tests/test_docs.py` does not fail, because it reduces a node id to its file and the file still exists. Only after the trace is regenerated do its claims fail, because the README, white paper and quad chart quote counts that have moved.

</details>

2. `make trace` exits 0 when a requirement is unverified. So what stops someone quietly marking a verified requirement `@Planned`?

<details><summary>Answer</summary>

An unverified requirement is a legitimate state, so the trace does not fail on it. The change still has to be committed: CI regenerates the trace and fails on any difference, so the new "unverified" row and the Planned table appear in the diff for review. And the README quotes the trace's counts through `tests/doc_claims.toml`, so `readme-trace-counts` fails until the prose admits the drop. A planned case whose evidence still exists also logs a warning.

</details>

3. Why record a known bug as a strict xfail rather than a skip, a plain xfail, or a comment?

<details><summary>Answer</summary>

A skip hides the behaviour and tests nothing. A comment is not executed. A plain xfail runs the test but lets a fix pass silently, so the marker and its reason outlive the bug. A strict xfail runs the test, shows its reason in every summary, and fails the suite as `XPASS(strict)` the day the bug is fixed, forcing the record to be updated. The control test next to it shows the xfail fails for the named reason, not some other one.

</details>

4. An AI tool module adds `from sentinel.conjunction import service`. The AI package imports nothing from `sentinel.risk` directly. Does `ai-does-no-math` still fail?

<details><summary>Answer</summary>

Yes. Forbidden contracts check indirect imports too, and the conjunction service imports `sentinel.cdm`, `sentinel.risk` and numpy, and reaches scipy through the engine. Import-linter reports that `sentinel.ai` is not allowed to import each of the four, with every chain that gets there. The AI layer is meant to reach the maths only through tool functions handed to it, never through an import.

</details>

5. Why does `make compliance` write the authored OSCAL documents before running pytest, and then generate from evidence after it?

<details><summary>Answer</summary>

The suite includes `test_committed_documents_are_what_the_sources_generate`. If pytest ran first, any edit to `compliance/sources/` would fail that test on its own first run, and the failure would be filed in the POA&M as staleness. Writing the authored documents first lets a source edit pass the first time. The evidence step has to come after pytest, because it reads the JUnit XML that pytest writes. `tests/compliance/test_make_compliance.py` holds both orderings.

</details>

6. A test cited by SI-7 is skipped in a CI run, and everything else passes. What do the assessment results and POA&M say?

<details><summary>Answer</summary>

The citation's state is `missing`, because a skip is not evidence. The control is observed but not satisfied, so the assessment results carry a finding for it. The POA&M gets an item titled "SI-7 cites evidence missing from the run", saying the check was renamed, deleted, skipped or not run. The run itself still passes pytest. The compliance evidence is what makes a skip visible.

</details>

7. `docs/traceability.md` reports every requirement verified. What exactly does that promise, and what does it not?

<details><summary>Answer</summary>

It promises that every requirement has at least one verification case, that none is `@Planned`, and that every piece of evidence those cases name exists: a collectable pytest id, a DDIL scenario marked PASS in the recorded report, an import contract, or a step or job in `ci.yml`. It does not promise that the tests passed in any particular run, that a CI job has ever run on a hosted runner, or that the harness report is fresh. Passing is shown by the test run and the OSCAL assessment results.

</details>

8. Why does `tests/test_docs.py` start by running each rule against a miniature repository with a planted fault?

<details><summary>Answer</summary>

A guard that silently checks nothing looks exactly like a guard that finds nothing wrong: both are green. Proving each rule reports a planted fault (a missing path, an unknown target, a moved number) shows the rule actually runs and can fail. Only then does a green result on the real documents mean something. The same idea appears in `KNOWN_BAD` for the SysML validator and in the signature self-test's lying-verifier check.

</details>

## Where next

- [Chapter 14: End to end](14-end-to-end.md): one CDM through the whole system, with the checks from this chapter at each step.
- [Chapter 12: Supply chain and deployment](12-supply-chain-and-deploy.md): the controls (SI-7, CM-14, RA-5, SR-11) whose evidence this package cites.
- [docs/compliance.md](../compliance.md): the package, the status counts, the tailoring and the largest gaps.
- [docs/traceability.md](../traceability.md): the generated trace, with its legend.
- [docs/risk-engine-design.md](../risk-engine-design.md), section 7: the full test ladder, rung by rung.
- [docs/technical-guide.md](../technical-guide.md) and `CONTRIBUTING.md`: which command to run before a pull request, for each kind of change.
