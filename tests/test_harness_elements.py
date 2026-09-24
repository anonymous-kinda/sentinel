"""Which element sets each harness node starts with.

The edge never loads its own: it must receive element sets from the hub
through sync, whatever the calling shell exports, or the OPSEC scenario's
"arrived through sync" would prove nothing. A conjunction-only hub loads an
empty snapshot, so the conjunction scenarios measure conjunction sync alone.
"""

import json
import pathlib
import shutil

import pytest

from harness.cluster import Cluster


@pytest.fixture
def cluster_dirs():
    made = []
    yield made
    for cluster in made:
        shutil.rmtree(cluster.dir, ignore_errors=True)


@pytest.mark.enable_socket  # Cluster allocates loopback ports only; no network access
def test_by_default_the_hub_loads_its_snapshot_and_the_edge_none(cluster_dirs, monkeypatch):
    monkeypatch.setenv("SENTINEL_ELEMENTS", "/somewhere/else.json")
    cluster = Cluster()
    cluster_dirs.append(cluster)
    env = cluster.elements_env()
    assert env == {"hub": {"SENTINEL_ELEMENTS": ""}, "edge": {"SENTINEL_ELEMENTS": ""}}


@pytest.mark.enable_socket
def test_a_conjunction_only_hub_starts_from_an_empty_snapshot(cluster_dirs):
    cluster = Cluster(hub_elements=False)
    cluster_dirs.append(cluster)
    env = cluster.elements_env()
    assert json.loads(pathlib.Path(env["hub"]["SENTINEL_ELEMENTS"]).read_text()) == []
    assert env["edge"] == {"SENTINEL_ELEMENTS": ""}
