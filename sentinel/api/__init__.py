"""HTTP API and the process that hosts a node (hub, edge or standalone)."""

from .app import create_app

__all__ = ["create_app"]
