# NIST SP 800-53 Rev 5 catalog: provenance

| | |
|---|---|
| Source | https://github.com/usnistgov/oscal-content |
| Release | `v1.5.0`, commit `78650f02ad9321bb7b817846f8fbd4f2bcd620de` |
| Upstream path | `nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog-min.json` |
| Retrieved | 2026-09-23 |
| Content | SP 800-53 Rev 5.2.0 controls and SP 800-53A Rev 5.2.0 assessment procedures, OSCAL 1.2.2 |
| Catalog UUID | `ea7c7688-79c5-463b-a91b-0650f2d98623` |
| Licence | Public domain in the United States (work of the U.S. Government); CC0 1.0 worldwide, per the repository's `LICENSE.md` |
| Integrity | `SHA256SUMS`, verified by `tests/compliance/test_package_integrity.py` and by `make compliance` before import |

The file is byte-for-byte unmodified. It is the minified form of
`NIST_SP-800-53_rev5_catalog.json` at the same commit; both parse to the
same JSON document (checked when this file was vendored).

## How it is used

`make compliance` verifies the checksum, then runs `trestle import` to place
the catalog in the workspace at
`compliance/oscal/catalogs/nist-800-53-rev5/catalog.json`. That copy is
build output (trestle re-serialises it, so its bytes differ) and is not
committed. The tailored profile (`compliance/oscal/profiles/sentinel/`)
imports it.

The tests read this vendored file directly to check that every control,
assessment objective and parameter the Sentinel profile names exists in
the catalog.
