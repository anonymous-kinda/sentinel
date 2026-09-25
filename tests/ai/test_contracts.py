"""The hosted SDKs stay in their two adapters (ADR-007, guard 6).

`lint-imports` enforces the `hosted-ai-at-the-edges` contract, but only
over the modules it lists. A module left off the list could import an SDK
and CI would pass, so this test holds the list to the package: every
module in `sentinel/ai`, the package's own `__init__` included, except the
two adapters.
"""

import configparser
import pathlib
import pkgutil

import sentinel.ai

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADAPTERS = {"sentinel.ai.router_jev", "sentinel.ai.narrate_claude"}


def _contract() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.read(ROOT / ".importlinter")
    return parser["importlinter:contract:hosted-ai-at-the-edges"]


def test_the_hosted_sdk_contract_covers_every_ai_module_but_the_two_adapters():
    modules = {"sentinel.ai"} | {f"sentinel.ai.{m.name}" for m in pkgutil.iter_modules(sentinel.ai.__path__)}
    contract = _contract()
    assert set(contract["source_modules"].split()) == modules - ADAPTERS
    assert set(contract["forbidden_modules"].split()) == {"typesafe_sdk", "anthropic"}


def test_listing_the_package_does_not_list_the_adapters_inside_it():
    """As a package, `sentinel.ai` would take in the adapters, and the
    contract would forbid them the SDKs they exist to wrap."""
    assert _contract()["as_packages"].strip().lower() == "false"
