# Documentation index

Every document in the repository: who it is for, whether a person writes it or a script generates it, and how to regenerate it. Never hand-edit a generated document. Change its inputs and run the command in the last column.

Three checks keep this set honest:
- `tests/docs/test_technical_guide.py` fails when a Markdown file in the repository is missing from this page.
- `tests/test_docs.py` checks every path, `make` target and `sentinel` subcommand named in `README.md`, `CLAUDE.md`, `SECURITY.md` and `docs/`.
- `tests/doc_claims.toml` registers each headline number the prose quotes, against the generated report or test it comes from.

Audiences: **new engineer** (has just cloned the repository), **reviewer** (judges the design or the evidence), **operator** (runs a node), **security** (ATO and supply-chain assessors), **acquisition** (program and mission stakeholders).

## Start here

| Document | Path | Audience | Authored or generated | Regenerate with |
|---|---|---|---|---|
| [README](../README.md) | `README.md` | everyone | authored | |
| [Technical guide](technical-guide.md) | `docs/technical-guide.md` | new engineer | authored; its variables, `make` targets, CLI subcommands, import contracts and paths are checked by `tests/docs/test_technical_guide.py`, and its quoted numbers are registered in `tests/doc_claims.toml` | |
| [Contributing](../CONTRIBUTING.md) | `CONTRIBUTING.md` | new engineer | authored; its paths, `make` targets and CLI subcommands are checked by `tests/docs/test_technical_guide.py` | |
| [Security policy](../SECURITY.md) | `SECURITY.md` | security, everyone | authored: how to report a vulnerability, and what is known to be missing | |
| [Repository rules for coding agents](../CLAUDE.md) | `CLAUDE.md` | new engineer, coding agents | authored | |
| This index | `docs/index.md` | everyone | authored | |
| [Licence](../LICENSE) | `LICENSE` | everyone | authored (Apache 2.0) | |

## Design

| Document | Path | Audience | Authored or generated | Regenerate with |
|---|---|---|---|---|
| [System design](system-design.md) | `docs/system-design.md` | reviewer, new engineer | authored: ADR-001 to ADR-012, with rejected alternatives | |
| [Risk engine design](risk-engine-design.md) | `docs/risk-engine-design.md` | reviewer, new engineer | authored: the maths and the test ladder | |
| [Wayfinder adapter](adapters/wayfinder.md) | `docs/adapters/wayfinder.md` | new engineer | authored: an assumed schema, and how to swap in the real one | |
| [Interface control index](icd/README.md) | `docs/icd/README.md` | new engineer, integrators | authored: every ICD, its standard and the test that keeps it current; checked by `tests/docs/test_icd_index.py` | |
| [HTTP API (OpenAPI 3.1)](icd/openapi.json) | `docs/icd/openapi.json` | new engineer, integrators | generated from the FastAPI app; `tests/docs/test_openapi_current.py` fails on a stale export | `make openapi` |
| [Bus and SSE messages (AsyncAPI 3.0)](icd/asyncapi.yaml) | `docs/icd/asyncapi.yaml` | new engineer, integrators | authored; held to the code both ways by `tests/docs/test_asyncapi.py` | |
| [CDM admission profile](icd/cdm-profile.md) | `docs/icd/cdm-profile.md` | new engineer, integrators | authored; held to the codec both ways by `tests/docs/test_cdm_profile.py` | |
| [Sync envelope](icd/sync-envelope.md) | `docs/icd/sync-envelope.md` | new engineer, integrators | authored; held to `sentinel/sync`, `sentinel/triage` and the adapters by `tests/docs/test_sync_envelope.py` | |
| [Pass API ICD](icd/passes-api.md) | `docs/icd/passes-api.md` | new engineer, integrators | authored; held to the code by `tests/api/test_passes_api.py` | |
| [Screening API ICD](icd/screening-api.md) | `docs/icd/screening-api.md` | new engineer, integrators | authored; held to the code by `tests/api/test_screening_api.py` | |

## Generated reports

| Document | Path | Audience | Authored or generated | Regenerate with |
|---|---|---|---|---|
| [Validation report](validation-report.md) | `docs/validation-report.md` | reviewer | generated from closed forms and NASA CARA's published values | `make report` |
| [DDIL results](ddil-results.md) | `docs/ddil-results.md` | reviewer, acquisition | generated from real two-node harness runs in `harness/results/` | `make ddil` (all six scenarios; needs the pinned tools from GitHub) |
| [AI routing eval](ai-eval.md) | `docs/ai-eval.md` | reviewer | generated from `evals/routing.jsonl`; Jev's column only from a real keyed run | `make ai-eval` |
| AI reliability diagram | `docs/img/ai-reliability.svg` | reviewer | generated with the AI routing eval | `make ai-eval` |
| [Requirements traceability](traceability.md) | `docs/traceability.md` | reviewer, security | generated from the SysML v2 model in `mbse/` and the evidence it names | `make trace` |

## Program documents

| Document | Path | Audience | Authored or generated | Regenerate with |
|---|---|---|---|---|
| [White paper](white-paper.md) | `docs/white-paper.md` | acquisition | authored; every proof-point number is registered in `tests/doc_claims.toml` against a generated report (`tests/docs/test_program_docs.py`) | |
| [Quad chart](quad-chart.md) | `docs/quad-chart.md`, `docs/quad-chart.svg` | acquisition | authored; the SVG gets the same drift guards as Markdown, and states no number the repository did not generate (`tests/docs/test_quad_chart.py`) | |
| [Demo script](demo-script.md) | `docs/demo-script.md` | operator, reviewer | authored: a three-minute walk-through on `make demo-local` | |
| [Install guide](install-guide.md) | `docs/install-guide.md` | operator | authored: installing a node at a disconnected or classified site, matching `deploy/bundle/` | |

## Deployment, supply chain and compliance

| Document | Path | Audience | Authored or generated | Regenerate with |
|---|---|---|---|---|
| [Deploying the cloud hub on AWS](deploy-aws.md) | `docs/deploy-aws.md` | operator | authored | |
| [Software supply chain](supply-chain.md) | `docs/supply-chain.md` | security, operator | authored | |
| [Compliance package](compliance.md) | `docs/compliance.md` | security | authored prose; its counts are checked against the sources by `tests/compliance/test_package_integrity.py` | |
| OSCAL profile, component definition, SSP and assessment plan | `compliance/oscal/profiles/sentinel/profile.json`, `compliance/oscal/component-definitions/sentinel/component-definition.json`, `compliance/oscal/system-security-plans/sentinel/system-security-plan.json`, `compliance/oscal/assessment-plans/sentinel/assessment-plan.json` | security | generated from `compliance/sources/*.toml` | `uv run python scripts/oscal_evidence.py` |
| OSCAL assessment results and POA&M | `compliance/oscal/assessment-results/sentinel/assessment-results.json`, `compliance/oscal/plan-of-action-and-milestones/sentinel/plan-of-action-and-milestones.json` | security | generated from a test run's evidence | `make compliance` |
| OSCAL sources | `compliance/sources/controls.toml`, `compliance/sources/stig.toml`, `compliance/sources/system.toml` | security | authored: the only hand-edited inputs to the OSCAL package | |
| OpenVEX document | `deploy/vex/sentinel.openvex.json` | security | generated from `deploy/vex/statements.toml` and a raw scan | `make vex` (downloads Trivy's database) |
| VEX statements | `deploy/vex/statements.toml` | security | authored: one reviewed statement per real finding, with checkable evidence | |

## Models

| Document | Path | Audience | Authored or generated | Regenerate with |
|---|---|---|---|---|
| SysML v2 requirements | `mbse/requirements.sysml` | reviewer | authored | |
| SysML v2 architecture and satisfaction | `mbse/sentinel.sysml` | reviewer | authored | |
| SysML v2 verification cases and evidence | `mbse/verification.sysml` | reviewer | authored; every piece of evidence it names is checked by `make trace` | |

## Data provenance

| Document | Path | Audience | Authored or generated | Regenerate with |
|---|---|---|---|---|
| [Fixtures overview](../fixtures/README.md) | `fixtures/README.md` | new engineer | authored | |
| [NASA CARA provenance](../fixtures/cara/PROVENANCE.md) | `fixtures/cara/PROVENANCE.md` | reviewer | authored | |
| [NASA CARA test-case notes](../fixtures/cara/PcTestCaseCDMs/README.md) | `fixtures/cara/PcTestCaseCDMs/README.md` | reviewer | vendored from NASA, unmodified | |
| [Element-set snapshots](../fixtures/omm/PROVENANCE.md) | `fixtures/omm/PROVENANCE.md` | reviewer | authored, with rows appended by `scripts/fetch_omm.py` | `uv run python scripts/fetch_omm.py resource` (network: CelesTrak) |
| [Wayfinder fixture provenance](../fixtures/wayfinder/PROVENANCE.md) | `fixtures/wayfinder/PROVENANCE.md` | reviewer | authored | |
| [NIST catalog provenance](../compliance/vendor/nist/PROVENANCE.md) | `compliance/vendor/nist/PROVENANCE.md` | security | authored | |
| [DISA STIG provenance](../compliance/vendor/disa/PROVENANCE.md) | `compliance/vendor/disa/PROVENANCE.md` | security | authored | |
| [Routing eval set](../evals/README.md) | `evals/README.md` | reviewer | authored: how the labels in `evals/routing.jsonl` were written, and their limits | |

## Images

| Document | Path | Audience | Authored or generated | Regenerate with |
|---|---|---|---|---|
| Console screenshots | `docs/img/console.png`, `docs/img/validation.png`, `docs/img/assistant.png`, `docs/img/edge-denied.png`, `docs/img/edge-sync.png`, `docs/img/edge-conflict.png`, `docs/img/passes.png` | everyone | captured by hand from a running node | no script; recapture from `make serve` or `make demo-local` |

## Being added (not yet on this branch)

Other work is finishing this document now. It is named here as plain text, not linked or quoted as a path, because it does not exist on this branch yet. When it lands, move it into the right group above, with a link.

| Document | Planned path | Audience |
|---|---|---|
| Container compose guide | docs/compose.md | operator |
