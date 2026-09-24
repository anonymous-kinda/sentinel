"""A node's role is one of three, and it reports sync only when it runs it.

An unknown SENTINEL_ROLE used to start no sync while /api/node still listed
a `sync` module: a misconfigured edge looked connected. The role is now
refused at start-up, and `sync` is reported only by a node whose sync
server or agent exists.
"""

import pytest
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.settings import ROLES, Settings


def modules(tmp_path, **settings) -> list[str]:
    app = create_app(
        Settings(exercise=False, library=False, web_dist=None, var_dir=str(tmp_path), **settings),
        start_background=False,
    )
    with TestClient(app) as client:
        return client.get("/api/node").json()["modules"]


def test_the_roles_are_hub_edge_and_standalone():
    assert ROLES == ("hub", "edge", "standalone")


@pytest.mark.parametrize("role", ["edg", "Hub", "", "leaf"])
def test_an_unknown_role_is_refused(role):
    with pytest.raises(ValueError, match=f"SENTINEL_ROLE must be one of hub, edge, standalone, not '{role}'"):
        Settings(role=role)


def test_an_unknown_role_in_the_environment_stops_the_node(monkeypatch):
    monkeypatch.setenv("SENTINEL_ROLE", "edg")
    with pytest.raises(ValueError, match="SENTINEL_ROLE"):
        create_app()


@pytest.mark.parametrize(
    ("settings", "runs_sync"),
    [
        ({"role": "standalone"}, False),
        ({"role": "hub", "node_id": "hub"}, True),
        ({"role": "edge", "node_id": "edge-alpha", "hub_id": "hub"}, True),
        ({"role": "edge", "node_id": "edge-alpha"}, False),
    ],
    ids=["standalone", "hub", "edge with a hub", "edge without a hub"],
)
def test_sync_is_reported_only_when_the_node_runs_it(tmp_path, settings, runs_sync):
    assert ("sync" in modules(tmp_path, **settings)) is runs_sync
