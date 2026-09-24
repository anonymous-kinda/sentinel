"""SBOM checks: an SBOM that misses what ships is a wrong answer, so it raises (CM-8)."""

import pytest

from supplychain.sbom import SbomError, component_names, require_components, syft_command

SPDX = {"spdxVersion": "SPDX-2.3", "packages": [{"name": "numpy"}, {"name": "sentinel"}]}
CDX = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"name": "react"}, {"name": "cesium"}]}


def test_names_come_from_spdx_packages_and_cyclonedx_components():
    assert component_names(SPDX) == {"numpy", "sentinel"}
    assert component_names(CDX) == {"react", "cesium"}


def test_cyclonedx_file_entries_are_not_counted_as_components():
    doc = {**CDX, "components": [*CDX["components"], {"type": "file", "name": "numpy/__init__.py"}]}
    assert component_names(doc) == {"react", "cesium"}


def test_an_unrecognised_document_raises():
    with pytest.raises(SbomError, match="neither SPDX nor CycloneDX"):
        component_names({"hello": "world"})


def test_a_complete_sbom_passes_and_reports_its_size():
    assert require_components(SPDX, {"numpy", "sentinel"}, "python") == 2


def test_a_missing_component_raises_and_names_it():
    with pytest.raises(SbomError, match="scipy"):
        require_components(SPDX, {"numpy", "scipy"}, "python")


def test_an_empty_sbom_raises_even_with_nothing_required():
    with pytest.raises(SbomError, match="no components"):
        require_components({"spdxVersion": "SPDX-2.3", "packages": []}, set(), "python")


def test_syft_writes_both_formats_from_one_catalog_pass():
    argv = syft_command(
        "syft", "stage/python", name="sentinel-python-runtime", version="0.2.0",
        outputs={"spdx-json": "a.spdx.json", "cyclonedx-json": "a.cdx.json"},
    )
    assert argv[:3] == ["syft", "scan", "dir:stage/python"]
    assert argv[argv.index("--source-name") + 1] == "sentinel-python-runtime"
    assert argv[argv.index("--source-version") + 1] == "0.2.0"
    outputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-o"]
    assert outputs == ["spdx-json=a.spdx.json", "cyclonedx-json=a.cdx.json"]
