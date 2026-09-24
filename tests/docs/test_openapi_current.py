"""docs/icd/openapi.json is the node's HTTP interface, exported from the app.

The committed file must equal a fresh export, so a route cannot change
without its interface control document changing in the same commit.
Regenerate it with `make openapi`; never hand-edit it.
"""

import dataclasses
import json

from scripts.export_openapi import OUTPUT, drift, export, render
from sentinel.cdm import CdmWarning
from sentinel.conjunction.service import IngestResult

# Owned by the pass module (docs/icd/passes-api.md); documented there.
PASS_ROUTES = "/api/passes"


def test_the_export_is_deterministic():
    assert render(export()) == render(export())


def test_the_committed_openapi_matches_a_fresh_export():
    problems = drift(OUTPUT.read_text(), render(export()))
    assert problems == [], f"docs/icd/openapi.json is stale ({problems}); run `make openapi`"


def test_drift_names_what_a_stale_document_is_missing():
    fresh = render(export())
    stale = json.loads(fresh)
    del stale["paths"]["/api/health"]
    stale["info"]["version"] = "0.0.0"
    assert drift(render(stale), fresh) == ["info differs", "paths./api/health differs"]
    assert drift(fresh, fresh) == []


def test_drift_catches_a_formatting_only_edit():
    fresh = render(export())
    assert drift(fresh.replace("\n", "\n ", 1), fresh) == ["formatting differs"]


def operations(spec: dict):
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            yield path, method, operation


def test_every_operation_is_tagged_summarised_and_described():
    undocumented = [
        f"{method.upper()} {path}"
        for path, method, op in operations(export())
        if not path.startswith(PASS_ROUTES)
        and not (op.get("tags") and op.get("summary") and op.get("description"))
    ]
    assert undocumented == []


def field_names(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def test_the_ingest_result_schema_is_the_ingest_result():
    # The route returns dataclasses.asdict(IngestResult); the documented schema
    # is written by hand, so it is held to the dataclass here.
    responses = export()["paths"]["/api/ingest/cdm"]["post"]["responses"]
    for status in ("200", "201", "422"):
        schema = responses[status]["content"]["application/json"]["schema"]
        assert set(schema["properties"]) == field_names(IngestResult), status
        assert set(schema["properties"]["warnings"]["items"]["properties"]) == field_names(CdmWarning), status
