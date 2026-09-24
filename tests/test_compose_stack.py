"""deploy/compose/compose.yaml, checked statically.

CI runs the stack live (ci.yml, job compose-smoke). These tests hold the
file to what that run depends on, without Docker:

- it is valid Compose (the compose-spec JSON schema, vendored and pinned);
- every pulled image is pinned by digest at the version tools.lock pins;
- only the two consoles are published, on the host's loopback;
- the edge reaches the hub only through Toxiproxy;
- each node's state stays in its own volume, and the edge's never mounts
  on the hub side (the unit's position rests there; ADR-010);
- every container is non-root, read-only and drops every capability.
"""

import copy
import hashlib
import json
import re
from urllib.parse import urlparse

import pytest
import yaml
from jsonschema import Draft202012Validator

from harness import compose
from harness.cluster import EDGE_ID, HUB_ID
from supplychain.toolslock import read_lock

SCHEMA_DIR = compose.COMPOSE_DIR / "schema"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
NODES = ("hub", "edge")
NODE_USER = "65532:65532"
STATE = "/var/lib/sentinel"
TRUST_DIR = f"{STATE}/trust"


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(compose.COMPOSE_FILE.read_text())


@pytest.fixture(scope="module")
def services(spec) -> dict:
    return spec["services"]


def schema() -> dict:
    return json.loads((SCHEMA_DIR / "compose-spec.json").read_text())


def env(service: dict) -> dict:
    return {k: str(v) for k, v in service.get("environment", {}).items()}


def mounts(service: dict) -> list[tuple[str, str, str]]:
    """(source, target, mode) for each short-syntax volume."""
    out = []
    for entry in service.get("volumes", []):
        source, target, *mode = entry.split(":")
        out.append((source, target, mode[0] if mode else "rw"))
    return out


def networks(service: dict) -> set[str]:
    return set(service.get("networks", []))


# ------------------------------------------------------------------- schema
def test_the_vendored_schema_is_the_file_its_checksum_names():
    sums = dict(reversed(line.split()) for line in (SCHEMA_DIR / "SHA256SUMS").read_text().splitlines())
    assert hashlib.sha256((SCHEMA_DIR / "compose-spec.json").read_bytes()).hexdigest() == sums["compose-spec.json"]


def test_the_schema_provenance_records_its_source_commit_and_digest():
    provenance = (SCHEMA_DIR / "PROVENANCE.md").read_text()
    digest = hashlib.sha256((SCHEMA_DIR / "compose-spec.json").read_bytes()).hexdigest()
    assert "https://github.com/compose-spec/compose-spec" in provenance
    assert re.search(r"\b[0-9a-f]{40}\b", provenance), "the source commit, in full"
    assert digest in provenance


def test_compose_yaml_is_valid_against_the_compose_spec_schema(spec):
    errors = [f"{list(e.absolute_path)}: {e.message}" for e in Draft202012Validator(schema()).iter_errors(spec)]
    assert errors == []


def test_the_schema_check_rejects_a_misspelt_key(spec):
    """Control: the validation above would catch a real mistake."""
    broken = copy.deepcopy(spec)
    broken["services"]["hub"]["helthcheck"] = broken["services"]["hub"].pop("healthcheck")
    assert list(Draft202012Validator(schema()).iter_errors(broken))


# ------------------------------------------------------------------- images
def test_every_pulled_image_is_pinned_by_digest(services):
    pulled = {name: s["image"] for name, s in services.items() if "build" not in s}
    assert pulled and all(DIGEST.search(image) for image in pulled.values()), pulled


def test_nats_and_toxiproxy_are_the_versions_tools_lock_pins(services):
    pinned = {pin.name: pin.version for pin in read_lock(compose.ROOT / "deploy" / "tools.lock")}
    tags = {name: s["image"].split("@")[0].rsplit(":", 1)[1] for name, s in services.items() if "build" not in s}
    assert tags["hub-nats"] == tags["edge-nats"] == f"{pinned['nats-server']}-scratch"
    assert tags["toxiproxy"] == pinned["toxiproxy"]


def test_every_sentinel_container_runs_the_one_image_built_from_this_checkout(services):
    built = {name: s for name, s in services.items() if "build" in s}
    assert set(built) == {"hub", "edge", "hub-identity", "edge-identity"}
    assert {s["image"] for s in built.values()} == {"sentinel-compose:local"}
    for s in built.values():
        assert s["build"] == {"context": "../..", "dockerfile": "deploy/compose/Dockerfile"}


# -------------------------------------------------------------------- ports
def test_only_the_two_consoles_are_published_and_only_on_the_host_loopback(services):
    published = {name: s["ports"] for name, s in services.items() if "ports" in s}
    assert published == {"hub-nats": ["127.0.0.1:8000:8000"], "edge-nats": ["127.0.0.1:8001:8000"]}
    assert (compose.HUB_CONSOLE, compose.EDGE_CONSOLE) == ("http://127.0.0.1:8000", "http://127.0.0.1:8001")


def test_each_node_shares_its_nats_servers_network_namespace(services):
    """So the configs' loopback listeners mean what they mean on a host, and
    each console is published by the container that owns the namespace."""
    assert services["hub"]["network_mode"] == "service:hub-nats"
    assert services["edge"]["network_mode"] == "service:edge-nats"
    for node in NODES:
        assert env(services[node])["SENTINEL_NATS_URL"] == f"nats://127.0.0.1:{compose.NATS_CLIENT_PORT}"


# --------------------------------------------------------------------- link
def test_the_edge_reaches_the_hub_only_through_toxiproxy(services):
    hub_side, edge_side = networks(services["hub-nats"]), networks(services["edge-nats"])
    assert hub_side and edge_side and not hub_side & edge_side
    assert networks(services["toxiproxy"]) == hub_side | edge_side
    on_both = [n for n, s in services.items() if networks(s) & hub_side and networks(s) & edge_side]
    assert on_both == ["toxiproxy"]
    leaf_url = re.search(r'url: "([^"]+)"', (compose.COMPOSE_DIR / "nats" / "edge.conf").read_text()).group(1)
    proxy = json.loads((compose.COMPOSE_DIR / "toxiproxy.json").read_text())[0]
    assert urlparse(leaf_url).hostname == "toxiproxy"
    assert urlparse(leaf_url).port == int(proxy["listen"].rsplit(":", 1)[1])
    assert proxy["upstream"] == f"hub-nats:{compose.HUB_LEAF_PORT}"


def test_containers_off_the_two_networks_have_none_or_a_nodes_namespace(services):
    for name, s in services.items():
        if not networks(s):
            assert s["network_mode"] in ("none", "service:hub-nats", "service:edge-nats"), name


def test_each_nats_server_and_toxiproxy_run_the_rendered_configs(spec, services):
    sources = {name: c["file"] for name, c in spec["configs"].items()}
    assert sorted(sources.values()) == sorted(f"./{name}" for name in compose.rendered())
    for service, target_flag in (("hub-nats", "--config"), ("edge-nats", "--config"), ("toxiproxy", "-config")):
        (config,) = services[service]["configs"]
        assert sources[config["source"]].endswith({"hub-nats": "hub.conf", "edge-nats": "edge.conf",
                                                   "toxiproxy": "toxiproxy.json"}[service])
        command = " ".join(services[service]["command"]).replace("=", " ")
        assert f"{target_flag} {config['target']}" in command


# ------------------------------------------------------------ roles and env
def test_the_hub_is_a_hub_and_the_edge_an_edge_with_link_controls(services):
    hub, edge = env(services["hub"]), env(services["edge"])
    assert (hub["SENTINEL_NODE_ID"], hub["SENTINEL_ROLE"]) == (HUB_ID, "hub")
    assert (edge["SENTINEL_NODE_ID"], edge["SENTINEL_ROLE"], edge["SENTINEL_HUB_ID"]) == (EDGE_ID, "edge", HUB_ID)
    assert edge["SENTINEL_DEMO_CONTROLS"] == "1" and "SENTINEL_DEMO_CONTROLS" not in hub
    assert edge["SENTINEL_TOXIPROXY_API"] == "http://toxiproxy:8474"


def test_the_node_ids_are_the_nats_server_names():
    for name, node in (("hub.conf", HUB_ID), ("edge.conf", EDGE_ID)):
        assert f'server_name: "{node}"' in (compose.COMPOSE_DIR / "nats" / name).read_text()


def test_both_nodes_are_marked_exercise_and_only_the_hub_runs_the_exercise(services):
    for node in NODES:
        assert "EXERCISE" in env(services[node])["SENTINEL_MARKING"]
    assert env(services["hub"])["SENTINEL_EXERCISE"] == "1"
    assert env(services["edge"])["SENTINEL_EXERCISE"] == "0", "the edge gets its events from the hub"


def test_both_nodes_have_a_healthcheck_on_api_health(services):
    for node in NODES:
        check = services[node]["healthcheck"]
        assert check["test"][0] == "CMD"
        assert "http://127.0.0.1:8000/api/health" in " ".join(check["test"])


# -------------------------------------------------------------------- state
def test_each_node_keeps_its_state_in_its_own_named_volume(spec, services):
    assert (f"{HUB_ID}-var", STATE, "rw") in mounts(services["hub"])
    assert ("edge-var", STATE, "rw") in mounts(services["edge"])
    assert {"hub-var", "edge-var", "trust"} <= set(spec["volumes"])


def test_the_edge_state_never_mounts_on_the_hub_side(services):
    """The unit's position rests in the edge's var dir: nothing else sees it."""
    users = {volume: sorted(name for name, s in services.items() if any(m[0] == volume for m in mounts(s)))
             for volume in ("edge-var", "hub-var")}
    assert users == {"edge-var": ["edge", "edge-identity"], "hub-var": ["hub", "hub-identity"]}


def test_nodes_read_a_trust_file_they_cannot_write(services):
    for node in NODES:
        assert ("trust", TRUST_DIR, "ro") in mounts(services[node])
        assert env(services[node])["SENTINEL_TRUST_FILE"] == f"{TRUST_DIR}/trust.json"


def test_each_identity_is_enrolled_by_the_harness_script_with_only_its_own_state(services):
    for node_id, service, volume in ((HUB_ID, "hub-identity", "hub-var"), (EDGE_ID, "edge-identity", "edge-var")):
        s = services[service]
        assert s["network_mode"] == "none"
        (script,) = [m for m in mounts(s) if m[0].endswith(".py")]
        assert (compose.COMPOSE_DIR / script[0]).resolve() == compose.ROOT / "harness" / "identity.py"
        assert script[2] == "ro"
        assert s["command"] == [node_id, STATE, f"{TRUST_DIR}/trust.json"]
        assert {m[:2] for m in mounts(s) if m != script} == {(volume, STATE), ("trust", TRUST_DIR)}


def test_nodes_start_only_after_both_identities_are_in_the_trust_file(services):
    done = {"condition": "service_completed_successfully"}
    for node in NODES:
        depends = services[node]["depends_on"]
        assert depends["hub-identity"] == done and depends["edge-identity"] == done
    assert services["edge-identity"]["depends_on"] == {"hub-identity": done}, "one writer at a time"


# ---------------------------------------------------------------- hardening
def test_every_container_is_non_root_read_only_and_unprivileged(services):
    for name, s in services.items():
        assert s["user"] == NODE_USER, name
        assert s["read_only"] is True, name
        assert s["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in s["security_opt"], name
        assert "privileged" not in s and "cap_add" not in s, name


def test_sentinel_containers_get_a_private_tmp_on_their_read_only_root(services):
    for name, s in services.items():
        if "build" in s:
            assert s["tmpfs"] == ["/tmp"], name
