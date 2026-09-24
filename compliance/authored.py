"""Profile, component definition, SSP and assessment plan, from the authored sources.

Each builder is a pure function of `Sources`. The statements, statuses and
evidence live once, in controls.toml; the component definition and the SSP
are two views of them.
"""

from __future__ import annotations

from typing import Any

from .oscal_common import (
    CATALOG,
    PROFILE,
    SSP,
    component_uuid,
    document,
    evidence_props,
    href,
    metadata,
    prop,
    stable_uuid,
    system_id,
    tool_uuid,
    without_empty,
)
from .sources import Contribution, Sources


def _meta(sources: Sources, title: str, **extra: Any) -> dict[str, Any]:
    doc = sources.system.document
    return metadata(title, doc.version, doc.last_modified, **extra)


# -------------------------------------------------------------------- profile
def build_profile(sources: Sources) -> dict[str, Any]:
    controls = sources.controls
    set_parameters = [
        {"param-id": param, "values": [value]} for control in controls for param, value in control.params.items()
    ]
    alters = [
        {"control-id": c.id, "adds": [{"position": "ending", "props": [prop("tailoring-rationale", c.rationale)]}]}
        for c in controls
    ]
    return document("profile", {
        "metadata": _meta(sources, f"{sources.system.name} tailored baseline: NIST SP 800-53 Rev 5"),
        "imports": [{"href": href(CATALOG), "include-controls": [{"with-ids": [c.id for c in controls]}]}],
        "merge": {"as-is": True},
        "modify": without_empty({"set-parameters": set_parameters, "alters": alters}),
    })


# --------------------------------------------------------- component definition
def build_component_definition(sources: Sources) -> dict[str, Any]:
    return document("component-definition", {
        "metadata": _meta(sources, f"{sources.system.name} component definition"),
        "components": [_defined_component(sources, c.key) for c in sources.system.components],
    })


def _defined_component(sources: Sources, key: str) -> dict[str, Any]:
    component = sources.system.component(key)
    requirements = [
        without_empty({
            "uuid": stable_uuid("component-requirement", key, control.id),
            "control-id": control.id,
            "description": contribution.statement,
            "props": [prop("implementation-status", contribution.status), *evidence_props(contribution)],
            "remarks": f"Plan: {contribution.plan}" if contribution.plan else "",
        })
        for control in sources.controls
        for contribution in control.contributions
        if contribution.component == key
    ]
    implementation = {
        "uuid": stable_uuid("control-implementation", key),
        "source": href(PROFILE),
        "description": f"What the {component.title} contributes to each control in the {sources.system.name} profile.",
        "implemented-requirements": requirements,
    }
    return without_empty({
        "uuid": component_uuid(key),
        "type": component.type,
        "title": component.title,
        "description": component.description,
        "control-implementations": [implementation] if requirements else [],
    })


# ------------------------------------------------------------------------ SSP
def build_ssp(sources: Sources) -> dict[str, Any]:
    system = sources.system
    parties = [{"uuid": stable_uuid("party", p.key), "type": p.type, "name": p.name} for p in system.parties]
    responsible = [
        {"role-id": role, "party-uuids": [stable_uuid("party", p.key) for p in system.parties if role in p.roles]}
        for role, _ in system.roles
        if any(role in p.roles for p in system.parties)
    ]
    return document("system-security-plan", {
        "metadata": _meta(
            sources, f"{system.name} system security plan (draft)",
            roles=[{"id": role, "title": title} for role, title in system.roles],
            parties=parties,
            **{"responsible-parties": responsible},
        ),
        "import-profile": {"href": href(PROFILE)},
        "system-characteristics": _characteristics(sources),
        "system-implementation": without_empty({
            "users": [
                {"uuid": stable_uuid("user", u.key), "title": u.title, "description": u.description, "role-ids": list(u.roles)}
                for u in system.users
            ],
            "components": [
                {"uuid": component_uuid(c.key), "type": c.type, "title": c.title, "description": c.description,
                 "status": {"state": c.state}}
                for c in system.components
            ],
        }),
        "control-implementation": {
            "description": (
                f"How {system.name} meets each control in its tailored profile, component by component. "
                "Statements cite the evidence behind them; anything short of implemented carries its plan."
            ),
            "implemented-requirements": [
                {
                    "uuid": stable_uuid("ssp-requirement", control.id),
                    "control-id": control.id,
                    "props": [prop("implementation-status", control.status)],
                    "by-components": [_by_component(control.id, c) for c in control.contributions],
                    "remarks": f"Selected because: {control.rationale}",
                }
                for control in sources.controls
            ],
        },
    })


def _characteristics(sources: Sources) -> dict[str, Any]:
    system = sources.system
    impact = system.impact
    return without_empty({
        "system-ids": [system_id(system.short_name)],
        "system-name": system.name,
        "system-name-short": system.short_name,
        "description": system.description,
        "security-impact-level": {
            "security-objective-confidentiality": impact["confidentiality"],
            "security-objective-integrity": impact["integrity"],
            "security-objective-availability": impact["availability"],
        },
        "system-information": {
            "information-types": [
                {
                    "uuid": stable_uuid("information-type", i.title),
                    "title": i.title,
                    "description": i.description,
                    "confidentiality-impact": {"base": i.confidentiality},
                    "integrity-impact": {"base": i.integrity},
                    "availability-impact": {"base": i.availability},
                }
                for i in system.information_types
            ]
        },
        "status": without_empty({"state": system.state, "remarks": system.state_remarks}),
        "authorization-boundary": {"description": system.authorization_boundary},
        "network-architecture": {"description": system.network_architecture} if system.network_architecture else None,
        "data-flow": {"description": system.data_flow} if system.data_flow else None,
    })


def _by_component(control_id: str, contribution: Contribution) -> dict[str, Any]:
    return without_empty({
        "component-uuid": component_uuid(contribution.component),
        "uuid": stable_uuid("by-component", control_id, contribution.component),
        "description": contribution.statement,
        "props": evidence_props(contribution),
        "implementation-status": without_empty({"state": contribution.status, "remarks": contribution.plan}),
    })


# ------------------------------------------------------------ assessment plan
def build_assessment_plan(sources: Sources) -> dict[str, Any]:
    system = sources.system
    tools = [
        {"uuid": tool_uuid(m.key), "type": "software", "title": m.title, "description": m.description,
         "status": {"state": "operational"}}
        for m in system.assessments
    ]
    return document("assessment-plan", {
        "metadata": _meta(sources, f"{system.name} automated assessment plan"),
        "import-ssp": {"href": href(SSP)},
        "reviewed-controls": reviewed_controls(sources),
        "assessment-subjects": [
            {
                "type": "component",
                "include-subjects": [
                    {"subject-uuid": component_uuid(c.key), "type": "component"} for c in system.components
                ],
            }
        ],
        "assessment-assets": {
            "components": tools,
            "assessment-platforms": [
                {
                    "uuid": stable_uuid("assessment-platform", "ci"),
                    "title": "CI runner (GitHub Actions, ubuntu-24.04) and the hosts the STIG role manages",
                    "uses-components": [{"component-uuid": t["uuid"]} for t in tools],
                }
            ],
        },
        "tasks": [
            without_empty({
                "uuid": stable_uuid("assessment-task", m.key),
                "type": "action",
                "title": m.title,
                "description": m.description,
                "props": [prop("evidence-ci", job) for job in m.ci],
            })
            for m in system.assessments
        ],
    })


def reviewed_controls(sources: Sources) -> dict[str, Any]:
    return {"control-selections": [{"include-controls": [{"control-id": c.id} for c in sources.controls]}]}
