"""Registry for subcommands contributed by later modules.

Kept separate so the core CLI (assess, cdm) has no import-time dependency
on the server, sync or mission modules.
"""

from __future__ import annotations


def register(sub) -> None:  # noqa: ARG001 - extended as modules land
    return None
