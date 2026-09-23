# Fixtures

`cara_cases.json` is intentionally absent.

Tier 3 of the test ladder validates the engine against NASA CARA's published
conjunction test cases. Those expected values must be **transcribed from
CARA's published material** - their released analysis tools and associated
papers - with provenance and retrieval date recorded per case.

Generating this file by running Sentinel would prove only that Sentinel
agrees with Sentinel. The Tier 3 tests are therefore skipped until the file
exists, and the skip is reported in the suite output.

The schema is documented in `tests/test_tier3_cara_validation.py`.
