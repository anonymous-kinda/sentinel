"""What element sets a node holds, and which it offers edges over sync.

A hub holds the whole public snapshot (screening needs it), but by default
offers edges only the imaging catalog the pass module uses: on a thin link
every record costs a round trip, and an edge cannot use the rest.
"""

import pytest

from sentinel.api.app import _sync_records, build_node
from sentinel.api.settings import Settings
from sentinel.passes.catalog import DEFAULT_CATALOG, load_catalog


def offered(node) -> set[int]:
    return {int(m["e"].removeprefix("omm:")) for m in _sync_records(node).manifest() if m["e"].startswith("omm:")}


@pytest.fixture
def catalog_ids() -> set[int]:
    return {imager.norad_id for imager in load_catalog(DEFAULT_CATALOG)}


def test_a_hub_holds_every_element_set_but_offers_only_the_imaging_catalog(tmp_path, catalog_ids):
    node = build_node(Settings(role="hub", var_dir=str(tmp_path), web_dist=None))
    assert len(node.elements.latest()) == 167
    assert offered(node) == catalog_ids


def test_a_hub_can_be_told_to_offer_everything(tmp_path):
    node = build_node(Settings(role="hub", var_dir=str(tmp_path), web_dist=None, sync_elements="all"))
    assert len(offered(node)) == 167


def test_an_unknown_scope_is_refused(tmp_path):
    with pytest.raises(ValueError):
        build_node(Settings(role="hub", var_dir=str(tmp_path), web_dist=None, sync_elements="some"))
