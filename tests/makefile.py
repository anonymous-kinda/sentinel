"""What a `make` target would do, read without doing it: its recipe from a
dry run (`make -n`), and the help text `make help` prints for it."""

from __future__ import annotations

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def dry_run(target: str) -> list[str]:
    """The commands `make <target>` would run, prerequisites first, without running them."""
    done = subprocess.run(["make", "-n", "--no-print-directory", target], cwd=ROOT,
                          capture_output=True, text=True, check=True)
    return done.stdout.splitlines()


def help_text(target: str) -> str:
    """The `## ...` help on the target's rule line, as `make help` prints it."""
    match = re.search(rf"^{re.escape(target)}:.*?## (.*)$", (ROOT / "Makefile").read_text(), re.MULTILINE)
    assert match, f"make {target} has no help text"
    return match[1]
