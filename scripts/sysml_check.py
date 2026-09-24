#!/usr/bin/env python3
"""Parse SysML v2 files with the pilot implementation's grammar (via sysml2py).

    make sysml-check

Runs in an isolated environment that has sysml2py; the project's own
environment does not (sysml2py pins astropy<6, which has no Python 3.13
wheels). Exit 1 on a syntax error, 2 if the validator is missing or accepts
a known-bad model. See mbse/syntax.py.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mbse.syntax import main  # noqa: E402
from sentinel.obs import configure_logging  # noqa: E402

if __name__ == "__main__":
    configure_logging()
    sys.exit(main(sys.argv[1:]))
