# Interface control documents

These documents are for engineers integrating with a Sentinel node, and for
reviewers checking that its interfaces are real and open. That is design
principle 4, standards at the seams (`docs/system-design.md`): each boundary
could be reimplemented or competed against a published contract.

Each document is tied to the code by a test, so it cannot drift silently. If
an interface changes without its ICD, CI fails.

## Documents

| Document | Interface | Standard | Kept current by |
|---|---|---|---|
| `openapi.json` | A node's HTTP API: every route, including the pass and screening modules'. | OpenAPI 3.1 | Generated from the FastAPI app by `make openapi` (`scripts/export_openapi.py`). `tests/docs/test_openapi_current.py` fails when the committed file differs from a fresh export. |
| `asyncapi.yaml` | The message bus: node-local events, the hub's request/reply subjects, every header and payload, and what may cross the leaf link. | AsyncAPI 3.0, NATS binding | `tests/docs/test_asyncapi.py`. Subjects, headers and the leaf policy are compared with the code and `deploy/nats/edge.conf.tmpl` both ways, and every message a real hub and edge send must validate against the document. |
| `cdm-profile.md` | CDM admission at the ADR-001 seam: required and used keywords, units, frames, rejection and warning codes, event identity, data-class marks. | A profile of CCSDS 508.0-B-1 (KVN) | `tests/docs/test_cdm_profile.py`. Every code, frame, unit rule and mark is compared with the codec both ways. |
| `sync-envelope.md` | The hub-to-edge priority pull and the operator-data exchange: summary fields, P0 to P4 and EDF, headers, verification states, and how a mission module plugs in. | None published. Local, influenced by DTN Bundle Protocol store-carry-forward without implementing BPv7. | `tests/docs/test_sync_envelope.py`. Fields, classes, states, headers, protocol methods and item-id prefixes are compared with `sentinel/sync`, `sentinel/triage` and the modules' adapters. |
| `passes-api.md` | The pass module's HTTP routes, all edge-local. | Written by hand; the routes are also in `openapi.json`. | `tests/api/test_passes_api.py` |
| `screening-api.md` | Demonstration-mode screening over HTTP (ADR-002): geometry only, filed as DERIVED CDMs, never a Pc. | Written by hand; the route is also in `openapi.json`. | `tests/api/test_screening_api.py` |

## Standards, and where there is none

- **HTTP:** OpenAPI 3.1, generated. The code is the source, so the document
  cannot disagree with it. The routes that read their own body declare it
  in `sentinel/api/apidoc.py`; that declaration is documentation only.
- **Bus:** AsyncAPI 3.0, NATS protocol binding. No AsyncAPI validator is
  available offline (the reference one is the JavaScript `@asyncapi/parser`),
  so `tests/docs/test_asyncapi.py` checks the structure the document relies
  on: version, `$ref`s, parameters, and operation and reply messages.
- **CDM:** CCSDS 508.0-B-1 is the standard. The profile says what Sentinel
  requires, uses and refuses, and says openly where DERIVED CDMs depart from it.
- **Sync envelope:** no published standard, and the document says so.
- **Element sets** travel as CelesTrak's JSON encoding of CCSDS OMM keywords,
  byte for byte. They are an `omm:` record in the sync envelope.

## Keeping them current

- `make openapi` regenerates `openapi.json`. Never hand-edit it.
- `make icd` regenerates it and runs every drift test in `tests/docs`.
- The drift tests read their facts from the code by import or AST, never
  from a copy. Each one is paired with a test showing it fails on a stale
  copy of its document.
- **A new node-local event** needs its kind registered in `NODE_EVENTS`
  (`sentinel/bus/subjects.py`; an unregistered kind raises) and its channel
  and message added to `asyncapi.yaml`.
- **A new interface** needs its document, a drift test, and a row in the
  table above. `tests/docs/test_icd_index.py` fails on an unindexed file.
