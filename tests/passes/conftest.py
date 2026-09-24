"""Shared fixtures for the pass-engine tests: the vendored snapshot and the
shipped catalog paired with it."""

import pytest

from sentinel.passes.catalog import load_catalog
from sentinel.passes.elements import load_omm, match_catalog

from .exercise import SNAPSHOT


@pytest.fixture(scope="session")
def snapshot():
    return load_omm(SNAPSHOT)


@pytest.fixture(scope="session")
def catalog_match(snapshot):
    return match_catalog(load_catalog(), snapshot)


@pytest.fixture(scope="session")
def by_name(catalog_match):
    return {imager.name: imager for imager in catalog_match.imagers}
