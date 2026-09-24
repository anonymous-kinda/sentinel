#!/usr/bin/env python3
"""Generate docs/traceability.md from the SysML v2 model in mbse/.

    uv run python scripts/trace.py        (or: make trace)

Every pytest node id the model names is checked against
`pytest --collect-only -q`, offline. Exit 1 on a broken reference (the file
still says which), 2 if the model cannot be read. See mbse/generate.py.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mbse.generate import main  # noqa: E402
from sentinel.obs import configure_logging  # noqa: E402

if __name__ == "__main__":
    configure_logging()
    sys.exit(main())
