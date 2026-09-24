"""Routers contributed by modules beyond the conjunction core.

Each entry is a callable (app, node) -> None. Keeping the list here, rather
than importing modules from app.py, lets a deployment profile (e.g. the
public read-only node) run without them.
"""

REGISTRARS: list = []
