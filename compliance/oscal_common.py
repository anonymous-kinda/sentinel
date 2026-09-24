"""What every generated OSCAL document shares: identity, metadata, props, paths.

Identity is deterministic. An object's uuid is derived from a stable key
(the control, the component, the POA&M item), so it survives regeneration
and can be tracked across runs. A document's uuid is derived from its content,
so it changes exactly when the document does, as OSCAL asks.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

from .sources import Contribution

OSCAL_VERSION = "1.2.1"  # the version compliance-trestle 5.1 validates against
NS = "urn:sentinel:oscal"  # namespace of every Sentinel-specific prop
RFC4122 = "https://ietf.org/rfc/rfc4122"
_ROOT = uuid.UUID("3f1c9e52-5d0a-4b8e-9a51-6c2d7e0b4f13")

# Workspace layout: compliance/oscal/<model dir>/<name>/<model>.json.
CATALOG = "catalogs/nist-800-53-rev5/catalog.json"
PROFILE = "profiles/sentinel/profile.json"
COMPONENT_DEFINITION = "component-definitions/sentinel/component-definition.json"
SSP = "system-security-plans/sentinel/system-security-plan.json"
ASSESSMENT_PLAN = "assessment-plans/sentinel/assessment-plan.json"
ASSESSMENT_RESULTS = "assessment-results/sentinel/assessment-results.json"
POAM = "plan-of-action-and-milestones/sentinel/plan-of-action-and-milestones.json"


def href(document: str) -> str:
    """Reference to another workspace document.

    trestle resolves imports (an SSP's profile, for one) against the workspace
    root, not against the importing document, so plain relative paths fail
    `trestle validate`. `trestle://` is its scheme for the workspace root.
    """
    return f"trestle://{document}"


def stable_uuid(*key: str) -> str:
    return str(uuid.uuid5(_ROOT, "|".join(key)))


def component_uuid(key: str) -> str:
    return stable_uuid("component", key)


def tool_uuid(assessment_key: str) -> str:
    """The assessment-plan asset (pytest ladder, DDIL harness, STIG scan) behind an observation."""
    return stable_uuid("assessment", assessment_key)


def system_id(short_name: str) -> dict[str, str]:
    return {"identifier-type": RFC4122, "id": stable_uuid("system", short_name)}


def timestamp(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def prop(name: str, value: str) -> dict[str, str]:
    return {"name": name, "ns": NS, "value": value}


def metadata(title: str, version: str, last_modified: dt.datetime, **extra: Any) -> dict[str, Any]:
    return {
        "title": title,
        "last-modified": timestamp(last_modified),
        "version": version,
        "oscal-version": OSCAL_VERSION,
        **extra,
    }


def document(model: str, body: dict[str, Any]) -> dict[str, Any]:
    """Wrap a model body with a uuid derived from its content."""
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {model: {"uuid": stable_uuid(model, digest), **body}}


def evidence_props(contribution: Contribution) -> list[dict[str, str]]:
    """The evidence a contribution cites, as namespaced props (resolved by compliance.citations)."""
    cited = [
        ("evidence-test", contribution.tests),
        ("evidence-harness", contribution.harness),
        ("evidence-ci", contribution.ci),
        ("evidence-file", contribution.files),
        ("planned-evidence", contribution.planned_evidence),
        ("milestone", (contribution.milestone,) if contribution.milestone else ()),
    ]
    return [prop(name, value) for name, values in cited for value in values]


def without_empty(node: dict[str, Any]) -> dict[str, Any]:
    """Drop empty lists and strings: OSCAL forbids empty arrays and blank values."""
    return {k: v for k, v in node.items() if v not in ([], "", None)}
