"""`make tools` fetches what its callers run, and its help says so.

Its callers are `make demo-local`, `make opsec` and `make ddil`, which run
the harness cluster: two nats-server processes and Toxiproxy
(harness/cluster.py refuses to start without them). The supply-chain tools
have their own target (`make supply-tools`), and a bundle fetches the
binaries it ships itself.
"""

from tests.makefile import dry_run, help_text

LINK_TOOLS = ["nats-server", "toxiproxy"]


def fetched_by(target: str) -> list[str] | None:
    """The tool names the target passes to scripts/fetch_tools.py ([] means every
    pin), or None when the target fetches nothing."""
    line = next((line for line in dry_run(target) if "scripts/fetch_tools.py" in line), None)
    if line is None:
        return None
    words = line.split()
    return words[words.index("scripts/fetch_tools.py") + 1 :]


def test_make_tools_fetches_the_two_binaries_the_harness_runs():
    assert fetched_by("tools") == LINK_TOOLS


def test_its_callers_get_them_through_it():
    for caller in ("demo-local", "opsec", "ddil"):
        assert fetched_by(caller) == LINK_TOOLS, caller


def test_its_help_names_exactly_what_it_fetches():
    text = help_text("tools")
    assert all(tool in text for tool in LINK_TOOLS)
    assert "uv" not in text.split()
