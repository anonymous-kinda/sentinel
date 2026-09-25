"""The console listens only for events its node publishes.

`useStream` in web/src/api/client.ts registers a listener per event kind on
`/api/stream`, which carries this node's `node.<node_id>.>` bus events.
Every kind it listens for must be a node-local kind documented in
docs/icd/asyncapi.yaml, and test_asyncapi.py holds that list to the code
both ways. A listener for a kind nothing publishes fails here.
"""

import re

from .icd import ROOT, documented_node_kinds, load_asyncapi

CLIENT = ROOT / "web" / "src" / "api" / "client.ts"
_KINDS = re.compile(r"const kinds = \[(.*?)\];", re.DOTALL)
_STRING = re.compile(r"""["']([^"']+)["']""")


def console_kinds(source: str) -> set[str]:
    """The event kinds `useStream` listens for."""
    match = _KINDS.search(source)
    assert match, f"no `const kinds = [...]` in {CLIENT.relative_to(ROOT)}: this check can no longer read it"
    return set(_STRING.findall(match[1]))


def console_problems(source: str, doc: dict) -> list[str]:
    return [
        f"the console listens for {kind}, which is not a documented node-local event"
        for kind in sorted(console_kinds(source) - documented_node_kinds(doc))
    ]


def test_the_console_yields_the_kinds_it_is_known_to_listen_for():
    assert {"cdm.accepted", "ops.changed", "sync.arrival", "passes.updated"} <= console_kinds(CLIENT.read_text())


def test_every_kind_the_console_listens_for_is_published():
    assert console_problems(CLIENT.read_text(), load_asyncapi()) == []


def test_a_listener_for_a_kind_nothing_publishes_is_caught():
    extra = CLIENT.read_text().replace('"cdm.accepted",', '"cdm.accepted",\n      "made.up",', 1)
    assert console_problems(extra, load_asyncapi()) == [
        "the console listens for made.up, which is not a documented node-local event"
    ]
