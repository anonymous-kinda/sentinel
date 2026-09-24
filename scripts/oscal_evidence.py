#!/usr/bin/env python3
"""Generate Sentinel's OSCAL package from its authored sources and CI evidence.

    uv run python scripts/oscal_evidence.py                              # authored documents only
    uv run python scripts/oscal_evidence.py --junit build/compliance/junit.xml \\
        [--harness harness/results] [--xccdf build/stig/<host>/results.xml]

`make compliance` runs the tests, this script and `trestle validate -a`.
See compliance/cli.py for the options and docs/compliance.md for the package.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance.cli import main
from sentinel.obs import configure_logging

if __name__ == "__main__":
    configure_logging()
    sys.exit(main())
