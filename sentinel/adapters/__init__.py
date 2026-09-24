"""Source adapters: one external payload shape in, one Sentinel contract out.

Each adapter is the only code that knows its source's schema. Everything
downstream sees the standard contract (for ephemerides, a StateTable), so
swapping or adding a source is an adapter, not a rewrite (MOSA).
"""
