"""docs/icd/asyncapi.yaml (AsyncAPI 3.0) against the bus as the code uses it.

Drift. The node-local kinds are discovered from the code, not listed in
it: AST over sentinel/ and harness/ finds every `subjects.local(...)` call
(through the helpers and constants that feed it) and every literal
`node.<id>.<kind>` subject. Each kind is a documented channel, and each
documented node-local channel is a kind the code publishes. The same goes
for every `Sentinel-Kind` header value, every bus header name, and every
subject builder in sentinel/bus/subjects.py. A subject built from a value
the check cannot read fails it. The core never lists mission names; the
check reads the call sites. The leaf policy the document states is the
edge nats-server's, and each channel's crossing claim follows from it.

Behaviour. A hub and an edge run a real sync over a recording bus, and a
node's API applies a link preset. Every message they send, and every reply,
must validate against the channel and message the document gives it:
headers present, allowed and with the documented value, payload shape. And
every documented channel must be exercised, so none describes dead code.

Structure. No AsyncAPI validator is available offline (the reference one is
the JavaScript @asyncapi/parser, not installable here without a network),
so the structure the document relies on is checked directly: the version,
every $ref resolves, parameters match address placeholders, operations use
their own channel's messages, and every reply resolves.
"""

import asyncio
import copy
import dataclasses
import datetime as dt
import inspect
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.records import CompositeRecords
from sentinel.api.settings import Settings
from sentinel.bus import InProcessBus, Msg, subject_matches, subjects
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.store import ConjunctionStore
from sentinel.conjunction.sync_adapter import ConjunctionRecords
from sentinel.crdt import NodeKey, TrustStore, codec
from sentinel.linkstate import LinkMonitor
from sentinel.ops import OpsService
from sentinel.passes.element_store import ElementStore
from sentinel.passes.sync_adapter import ElementRecords
from sentinel.sync import SyncAgent, SyncServer

from .icd import (
    NODE_PREFIX,
    ROOT,
    Found,
    addresses,
    compare,
    documented_node_kinds,
    family,
    headers_read,
    load_asyncapi,
    nats_list,
    node_kinds,
    sentinel_kinds,
    sources,
    string_constants,
)

EDGE_CONF = ROOT / "deploy" / "nats" / "edge.conf.tmpl"
SNAPSHOT = ROOT / "fixtures" / "omm" / "celestrak-resource-20260924.json"
HEADER = r"(Sentinel|Nats)-[A-Za-z0-9]+(-[A-Za-z0-9]+)*"
# Not subject builders: a token sanitiser, the generic node-local builder
# (its kinds are found at its call sites) and the console's wildcard.
NOT_BUILDERS = {"token", "local", "local_all"}
EPOCH = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)


# ------------------------------------------------------------------ $ref
def resolve(doc: dict, ref: str):
    assert ref.startswith("#/"), f"only local refs: {ref}"
    node = doc
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def deref(doc: dict, node):
    while isinstance(node, dict) and "$ref" in node:
        node = resolve(doc, node["$ref"])
    return node


def refs(node):
    if isinstance(node, dict):
        if "$ref" in node:
            yield node["$ref"]
        for value in node.values():
            yield from refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from refs(value)


# ---------------------------------------------------------- the code's side
def template(builder) -> str:
    """A builder's subject with its parameters as {placeholders}."""
    names = list(inspect.signature(builder).parameters)
    return ".".join(f"{{{t}}}" if t in names else t for t in builder(*names).split("."))


def builders() -> dict:
    return {
        name: fn
        for name, fn in inspect.getmembers(subjects, inspect.isfunction)
        if fn.__module__ == subjects.__name__ and not name.startswith("_") and name not in NOT_BUILDERS
    }


def cross_node_families() -> set[str]:
    return {f for f in (family(template(fn)) for fn in builders().values()) if not f.startswith(NODE_PREFIX)}


@dataclasses.dataclass(frozen=True)
class CodeFacts:
    node_kinds: Found
    sentinel_kinds: Found
    headers: set[str]


def code_facts(scanned=None) -> CodeFacts:
    """What the code publishes: sentinel/ and harness/ unless told otherwise."""
    scanned = scanned if scanned is not None else sources("sentinel/**/*.py", "harness/*.py")
    modules = [source.module for source in scanned]
    return CodeFacts(
        node_kinds(scanned), sentinel_kinds(scanned), string_constants(modules, HEADER) | headers_read(modules)
    )


def code_headers() -> set[str]:
    return code_facts().headers


# ------------------------------------------------------- the document's side
def messages(doc: dict, channel: dict) -> dict[str, dict]:
    return {name: deref(doc, message) for name, message in channel["messages"].items()}


def all_messages(doc: dict) -> list[dict]:
    return [m for channel in doc["channels"].values() for m in messages(doc, channel).values()]


def header_schema(doc: dict, message: dict) -> dict:
    return deref(doc, message.get("headers", {}))


def documented_headers(doc: dict) -> set[str]:
    return {name for message in all_messages(doc) for name in header_schema(doc, message).get("properties", {})}


def kind_of(doc: dict, message: dict) -> str | None:
    return deref(doc, header_schema(doc, message).get("properties", {}).get("Sentinel-Kind", {})).get("const")


def documented_cross_node_families(doc: dict) -> set[str]:
    return {family(a) for a in addresses(doc).values() if not a.startswith(NODE_PREFIX)}


def documented_sentinel_kinds(doc: dict) -> set[str]:
    return {kind_of(doc, message) for message in all_messages(doc)} - {None}


def pattern(address: str) -> str:
    return ".".join("*" if t.startswith("{") else t for t in address.split("."))


def crossing_problems(doc: dict, deny_exports: set[str], deny_imports: set[str]) -> list[str]:
    problems = []
    for name, channel in doc["channels"].items():
        crosses = channel.get("x-sentinel-crosses-leaf")
        if channel.get("address") is None:
            if crosses is not True:
                problems.append(f"reply channel {name} must be marked as crossing (replies return by inbox)")
            continue
        subject = pattern(channel["address"])
        exported = not any(subject_matches(deny, subject) for deny in deny_exports)
        imported = not any(subject_matches(deny, subject) for deny in deny_imports)
        if crosses is not (exported and imported):
            problems.append(f"channel {name}: x-sentinel-crosses-leaf is {crosses}, the edge config says {exported and imported}")
    return problems


def unreadable(found: Found, what: str) -> list[str]:
    return [f"{what} at {where} is built from a value this check cannot read" for where in found.unresolved]


def asyncapi_problems(doc: dict, code: CodeFacts | None = None) -> list[str]:
    code = code or code_facts()
    documented = set(addresses(doc).values())
    problems = compare(documented_cross_node_families(doc), cross_node_families(), "subject family")
    problems += [
        f"builder {name} gives {template(fn)}, which is no channel's address"
        for name, fn in sorted(builders().items())
        if template(fn) not in documented
    ]
    problems += compare(documented_node_kinds(doc), code.node_kinds.values, "node event kind")
    problems += unreadable(code.node_kinds, "a node-local subject")
    problems += compare(documented_sentinel_kinds(doc), code.sentinel_kinds.values, "Sentinel-Kind")
    problems += unreadable(code.sentinel_kinds, "a Sentinel-Kind header")
    problems += compare(documented_headers(doc), code.headers, "header")
    if doc.get("x-sentinel-console-subscription") != template(subjects.local_all):
        problems.append(f"console subscription is not {template(subjects.local_all)}")
    policy = doc["x-sentinel-leaf-policy"]
    conf = EDGE_CONF.read_text()
    problems += compare(set(policy["deny_exports"]), nats_list(conf, "deny_exports"), "edge deny_exports")
    problems += compare(set(policy["deny_imports"]), nats_list(conf, "deny_imports"), "edge deny_imports")
    problems += crossing_problems(doc, set(policy["deny_exports"]), set(policy["deny_imports"]))
    return problems


# ------------------------------------------------------------- structure
def structure_problems(doc: dict) -> list[str]:
    problems = []
    if doc.get("asyncapi") != "3.0.0":
        problems.append("asyncapi is not 3.0.0")
    if not (doc.get("info", {}).get("title") and doc.get("info", {}).get("version")):
        problems.append("info needs title and version")
    for ref in refs(doc):
        try:
            resolve(doc, ref)
        except (KeyError, AssertionError, TypeError):
            problems.append(f"unresolved $ref {ref}")
    if problems:
        return problems
    for name, channel in doc["channels"].items():
        placeholders = {t[1:-1] for t in (channel.get("address") or "").split(".") if t.startswith("{")}
        if placeholders != set(channel.get("parameters", {})):
            problems.append(f"channel {name}: parameters do not match the address")
        if not channel.get("messages"):
            problems.append(f"channel {name} has no messages")
        for message_name, message in messages(doc, channel).items():
            if "payload" not in message:
                problems.append(f"message {name}.{message_name} has no payload")
            if "headers" in message and header_schema(doc, message).get("type") != "object":
                problems.append(f"message {name}.{message_name}: headers must be an object schema")
    for name, operation in doc["operations"].items():
        if operation.get("action") not in {"send", "receive"}:
            problems.append(f"operation {name}: action must be send or receive")
        channel_ref = operation["channel"]["$ref"]
        for message in operation.get("messages", []):
            if not message["$ref"].startswith(f"{channel_ref}/messages/"):
                problems.append(f"operation {name}: {message['$ref']} is not a message of its channel")
        reply = operation.get("reply")
        if reply:
            reply_ref = reply["channel"]["$ref"]
            for message in reply.get("messages", []):
                if not message["$ref"].startswith(f"{reply_ref}/messages/"):
                    problems.append(f"operation {name}: reply {message['$ref']} is not a message of its channel")
    return problems


# ------------------------------------------------------- message validation
TYPES = {"object": dict, "array": list, "string": (str, bytes), "integer": int, "number": (int, float),
         "boolean": bool, "null": type(None)}


def type_ok(expected, value) -> bool:
    names = expected if isinstance(expected, list) else [expected]
    return any(
        isinstance(value, TYPES[n]) and not (n in ("integer", "number") and isinstance(value, bool)) for n in names
    )


def check(doc: dict, schema: dict, value, where: str) -> list[str]:
    """The subset of JSON Schema the document uses: type, const, enum,
    required, properties, additionalProperties: false, items, maxLength."""
    schema = deref(doc, schema)
    if "type" in schema and not type_ok(schema["type"], value):
        return [f"{where}: {type(value).__name__} is not {schema['type']}"]
    problems = []
    if "const" in schema and value != schema["const"]:
        problems.append(f"{where}: {value!r} is not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        problems.append(f"{where}: longer than {schema['maxLength']}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        problems += [f"{where}: missing {key}" for key in schema.get("required", []) if key not in value]
        if schema.get("additionalProperties") is False:
            problems += [f"{where}: undocumented {key}" for key in sorted(set(value) - set(properties))]
        for key, sub in properties.items():
            if key in value:
                problems += check(doc, sub, value[key], f"{where}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value[:5]):
            problems += check(doc, schema["items"], item, f"{where}[{index}]")
    return problems


def decode(doc: dict, message: dict, data: bytes):
    content_type = message.get("contentType", doc["defaultContentType"])
    if not data or content_type == "application/octet-stream":
        return data
    if content_type == "application/cbor":
        return codec.decode(data)
    return json.loads(data)


def message_problems(doc: dict, message: dict, msg: Msg) -> list[str]:
    name = message.get("name", "?")
    problems = check(doc, header_schema(doc, message), dict(msg.headers), f"{name} headers")
    return problems + check(doc, message["payload"], decode(doc, message, msg.data), f"{name} payload")


def channel_for(doc: dict, subject: str) -> str | None:
    matches = [name for name, address in addresses(doc).items() if subject_matches(pattern(address), subject)]
    assert len(matches) <= 1, f"{subject} matches {matches}"
    return matches[0] if matches else None


def reply_channel_for(doc: dict, request_channel: str) -> str | None:
    for operation in doc["operations"].values():
        if operation["channel"]["$ref"] == f"#/channels/{request_channel}" and operation.get("reply"):
            return operation["reply"]["channel"]["$ref"].rsplit("/", 1)[1]
    return None


def conformance(doc: dict, recorded: list[tuple[str, Msg]]) -> tuple[list[str], set[str]]:
    """Problems with what was sent, and the channels it exercised."""
    problems, used = [], set()
    for direction, msg in recorded:
        channel = channel_for(doc, msg.subject)
        if channel and direction == "reply":
            channel = reply_channel_for(doc, channel)
        if channel is None:
            problems.append(f"{direction} on {msg.subject} has no documented channel")
            continue
        used.add(channel)
        candidates = [message_problems(doc, m, msg) for m in messages(doc, doc["channels"][channel]).values()]
        best = min(candidates, key=len)
        problems += [f"{direction} on {msg.subject}: {p}" for p in best]
    return sorted(set(problems)), used


# ----------------------------------------------------------- the real bus
class RecordingBus(InProcessBus):
    def __init__(self):
        super().__init__()
        self.recorded: list[tuple[str, Msg]] = []

    async def publish(self, subject, data, headers=None):
        self.recorded.append(("publish", Msg(subject, data, dict(headers or {}))))
        await super().publish(subject, data, headers)

    async def request(self, subject, data, timeout, headers=None):
        self.recorded.append(("request", Msg(subject, data, dict(headers or {}))))
        reply = await super().request(subject, data, timeout, headers)
        self.recorded.append(("reply", reply))
        return reply


KEYS = {n: NodeKey.generate(n) for n in ("hub", "alpha")}
TRUST = {n: k.public_hex() for n, k in KEYS.items()}


class Node:
    def __init__(self, node_id, bus, clock):
        self.conj = ConjunctionService(ConjunctionStore(), bus, clock, node_id=node_id)
        self.ops = OpsService(node_id, KEYS[node_id], TrustStore(TRUST), bus, clock, current_ref=self.conj.current_ref)
        self.elements = ElementStore()
        self.records = CompositeRecords(ConjunctionRecords(self.conj), {"omm:": ElementRecords(self.elements, clock)})


async def hub_and_edge(bus: RecordingBus) -> None:
    """Admission both ways, operator data, one full sync cycle, an unchanged
    manifest and a fetch the hub cannot answer."""
    clock = FixedClock(EPOCH + dt.timedelta(hours=1))
    hub, edge = Node("hub", bus, clock), Node("alpha", bus, clock)
    await SyncServer(bus, hub.records, hub.ops, "hub").start()
    for item in generate(EPOCH):
        if item.release_at <= clock.now():
            await hub.conj.ingest(item.kvn.encode(), "exercise", "EXERCISE")
    await hub.conj.ingest(b"not a CDM", "icd-test", "REAL")
    hub.elements.load_snapshot(SNAPSHOT, "celestrak")
    event_id = hub.conj.list_events()[0]["event_id"]
    await hub.ops.annotate(event_id, "triage_status", "WATCH", "op@hub")

    agent = SyncAgent(bus, edge.records, edge.ops, clock, "alpha", "hub", LinkMonitor(), interval_s=3600)
    cycle = asyncio.create_task(agent.run())
    for _ in range(500):
        if any(msg.subject.endswith(".sync.progress") for _, msg in bus.recorded):
            break
        await asyncio.sleep(0.01)
    cycle.cancel()
    await agent.fetch_manifest()
    await bus.request(subjects.sync_fetch("hub"), codec.encode({"sha": "0" * 16, "from": "alpha"}), 5.0)


class ToxiproxyApi:
    """Toxiproxy's REST API, in memory, so the real control code runs."""

    def __init__(self):
        self.proxy = {"enabled": True, "toxics": []}

    def __call__(self, method, path, body=None):
        if method == "DELETE":
            self.proxy["toxics"] = [t for t in self.proxy["toxics"] if t["name"] != path.rsplit("/", 1)[1]]
        elif method == "POST" and path.endswith("/toxics"):
            self.proxy["toxics"].append(body)
        elif method == "POST":
            self.proxy.update(body)
        return self.proxy


UNIT = {"unit_id": "EX-UNIT-1", "lat_deg": 35.26, "lon_deg": -116.68, "alt_m": 700.0, "reaction_time_min": 30.0}


def node_api(bus: RecordingBus, var_dir: pathlib.Path) -> None:
    """The node-local events only an API call raises: a link preset, a unit."""
    settings = Settings(exercise=False, library=False, web_dist=None, var_dir=str(var_dir), demo_controls=True)
    app = create_app(settings, clock=FixedClock(EPOCH), bus=bus, start_background=False)
    app.state.node.toxiproxy._call = ToxiproxyApi()
    with TestClient(app) as client:
        assert client.post("/api/demo/link", json={"preset": "LIMITED"}).status_code == 200
        assert client.put("/api/passes/unit", json=UNIT).status_code == 200


@pytest.fixture(scope="module")
def recorded(tmp_path_factory) -> list[tuple[str, Msg]]:
    bus = RecordingBus()
    asyncio.run(hub_and_edge(bus))
    node_api(bus, tmp_path_factory.mktemp("var"))
    return bus.recorded


# ------------------------------------------------------------------ tests
def test_the_code_yields_the_subjects_and_headers_it_is_known_to_use():
    code = code_facts()
    # One of each route to a kind: a builder's f-string (cdm.accepted), a
    # literal (ops.changed), a helper's callers (sync.arrival), a module
    # constant (passes.updated).
    assert {"cdm.accepted", "ops.changed", "sync.arrival", "passes.updated"} <= code.node_kinds.values
    assert code.node_kinds.unresolved == [] and code.sentinel_kinds.unresolved == []
    assert {"record.full", "sync.progress", "passes.updated"} <= code.sentinel_kinds.values
    assert {"Sentinel-Kind", "Sentinel-Event-Id", "Nats-Msg-Id"} <= code.headers
    assert "sync.{hub_id}.fetch" in cross_node_families()
    assert template(subjects.cdm_accepted) == "node.{node_id}.cdm.accepted.{event_id}"


def test_a_value_becomes_exactly_one_subject_token_as_documented():
    assert subjects.cdm_accepted("hub a", "X.Y>*") == "node.hub_a.cdm.accepted.X_Y__"


UNDOCUMENTED = '''
from sentinel.bus import subjects

REASON = "made.constant"
CANARY = "node.edge-x.made.literal"


async def direct(bus, node_id):
    await bus.publish(subjects.local(node_id, "made.direct"), b"{}", {"Sentinel-Kind": "made.direct"})


class Module:
    async def _emit(self, kind):
        await self.bus.publish(subjects.local(self.node_id, kind), b"{}", {"Sentinel-Kind": kind})

    async def changed(self):
        await self._emit("made.helper")

    async def constant(self):
        await self.bus.publish(subjects.local(self.node_id, REASON), b"{}")

    async def computed(self, name):
        await self.bus.publish(subjects.local(self.node_id, name.lower()), b"{}")
'''


def test_an_undocumented_node_local_kind_fails_the_check(tmp_path):
    (tmp_path / "module.py").write_text(UNDOCUMENTED)
    found = code_facts(sources(root=tmp_path))
    assert found.node_kinds.values == {"made.direct", "made.helper", "made.constant", "made.literal"}
    assert found.node_kinds.unresolved == ["module.py:23"]
    assert found.sentinel_kinds.values == {"made.direct", "made.helper"}

    real = code_facts()
    merged = CodeFacts(
        Found(real.node_kinds.values | found.node_kinds.values, found.node_kinds.unresolved),
        Found(real.sentinel_kinds.values | found.sentinel_kinds.values, []),
        real.headers,
    )
    assert asyncapi_problems(load_asyncapi(), merged) == [
        "node event kind made.constant is not documented",
        "node event kind made.direct is not documented",
        "node event kind made.helper is not documented",
        "node event kind made.literal is not documented",
        "a node-local subject at module.py:23 is built from a value this check cannot read",
        "Sentinel-Kind made.direct is not documented",
        "Sentinel-Kind made.helper is not documented",
    ]


def test_a_documented_kind_the_code_no_longer_publishes_fails_the_check():
    doc = load_asyncapi()
    doc["channels"]["retired"] = {
        **copy.deepcopy(doc["channels"]["cdmRejected"]),
        "address": "node.{node_id}.retired.kind",
        "messages": {"retired": {"$ref": "#/components/messages/retired"}},
    }
    doc["components"]["messages"]["retired"] = copy.deepcopy(doc["components"]["messages"]["cdmRejected"])
    doc["components"]["messages"]["retired"]["headers"]["properties"]["Sentinel-Kind"] = {"const": "retired.kind"}
    assert asyncapi_problems(doc) == [
        "node event kind retired.kind is documented but not in the code",
        "Sentinel-Kind retired.kind is documented but not in the code",
    ]


def test_the_document_is_structurally_asyncapi_3():
    assert structure_problems(load_asyncapi()) == []


def test_the_structure_check_catches_a_broken_document():
    doc = load_asyncapi()
    doc["channels"]["syncFetch"]["parameters"] = {}
    doc["operations"]["serveFetch"]["channel"] = {"$ref": "#/channels/noSuchChannel"}
    assert structure_problems(doc) == ["unresolved $ref #/channels/noSuchChannel"]
    doc["operations"]["serveFetch"]["channel"] = {"$ref": "#/channels/syncFetch"}
    assert structure_problems(doc) == ["channel syncFetch: parameters do not match the address"]


def test_the_document_matches_the_subjects_headers_and_leaf_policy_in_the_code():
    assert asyncapi_problems(load_asyncapi()) == []


def test_a_stale_document_is_caught():
    doc = load_asyncapi()
    stale = copy.deepcopy(doc)
    del stale["channels"]["syncArrival"]
    stale["operations"] = {k: v for k, v in stale["operations"].items() if "syncArrival" not in json.dumps(v)}
    assert asyncapi_problems(stale) == [
        "node event kind sync.arrival is not documented",
        "Sentinel-Kind sync.arrival is not documented",
    ]
    stale = copy.deepcopy(doc)
    stale["components"]["messages"]["cdmRejected"]["headers"]["properties"]["Sentinel-Retired"] = {"type": "string"}
    assert asyncapi_problems(stale) == ["header Sentinel-Retired is documented but not in the code"]
    stale = copy.deepcopy(doc)
    stale["channels"]["syncProgress"]["x-sentinel-crosses-leaf"] = True
    assert asyncapi_problems(stale) == [
        "channel syncProgress: x-sentinel-crosses-leaf is True, the edge config says False"
    ]


def test_every_message_the_nodes_send_is_the_documented_message(recorded):
    problems, _ = conformance(load_asyncapi(), recorded)
    assert problems == []


def test_every_documented_channel_is_exercised(recorded):
    doc = load_asyncapi()
    _, used = conformance(doc, recorded)
    assert sorted(set(doc["channels"]) - used) == []


def test_a_message_that_drifts_from_the_document_is_caught(recorded):
    doc = load_asyncapi()
    del doc["components"]["messages"]["record"]["headers"]["properties"]["Nats-Msg-Id"]
    doc["components"]["messages"]["cdmAccepted"]["headers"]["required"].append("Sentinel-Event-Id")
    problems, _ = conformance(doc, recorded)
    assert any("record headers: undocumented Nats-Msg-Id" in p for p in problems)
    assert any("cdm.accepted headers: missing Sentinel-Event-Id" in p for p in problems)
